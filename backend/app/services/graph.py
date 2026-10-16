"""Network graph, dependency graph, attack-path analysis and containment impact.

Reachability is derived from *policy*, not from drawn lines:

* Candidate edges are every modeled relationship (except L2 topology) plus every concrete
  (source, destination, service) implied by an active ALLOW policy (zone selectors are
  expanded to member assets). Each candidate is then evaluated by the policy engine, so a
  higher-priority deny always wins.
* An attacker who controls the entry asset can originate any permitted flow from it.
  Reaching further requires compromising an intermediate asset through the permitted
  service; such multi-hop paths are labelled HYPOTHETICAL.

Hop classification:
  DEMONSTRATED - permitted and actually observed since the last baseline reset
  PERMITTED    - allowed by policy, not observed
  HYPOTHETICAL - beyond the first hop (requires compromise of an intermediate asset)
Blocked edges are reported separately and never traversed.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Asset,
    NetworkRelationship,
    OperationalDependency,
    PolicyDecision,
    SecurityPolicy,
)
from app.models.enums import (
    CRITICALITY_RANK,
    Criticality,
    DecisionOutcome,
    PolicyEffect,
    PolicyType,
    RelationshipOrigin,
    RelationshipType,
)
from app.services.policy_engine import PolicyEngine, PolicyView, endpoint_for_asset

MAX_PATHS = 400


@dataclass(frozen=True)
class Edge:
    source: str
    destination: str
    service: str
    outcome: DecisionOutcome
    matched_policy_id: str | None
    reason: str
    relationship_id: int | None
    origin: str  # BASELINE | OBSERVED | POLICY_ONLY
    observed: bool

    @property
    def permitted(self) -> bool:
        return self.outcome is not DecisionOutcome.BLOCKED

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "destination": self.destination,
            "service": self.service,
            "outcome": self.outcome.value,
            "matched_policy_id": self.matched_policy_id,
            "reason": self.reason,
            "relationship_id": self.relationship_id,
            "origin": self.origin,
            "observed": self.observed,
        }


@dataclass
class GraphContext:
    """Snapshot of assets, relationships and (optionally hypothetical) policies."""

    assets: dict[str, Asset]
    relationships: list[NetworkRelationship]
    policies: list[PolicyView]
    engine: PolicyEngine
    _edges: list[Edge] | None = field(default=None, repr=False)

    @classmethod
    def load(
        cls,
        session: Session,
        extra_policies: Iterable[PolicyView] = (),
        deactivate_policy_ids: Iterable[str] = (),
    ) -> GraphContext:
        assets = {
            a.id: a
            for a in session.scalars(
                select(Asset).where(Asset.is_active.is_(True), Asset.is_logical.is_(False))
            )
        }
        relationships = [
            r
            for r in session.scalars(select(NetworkRelationship).order_by(NetworkRelationship.id))
            if r.source_asset_id in assets and r.destination_asset_id in assets
        ]
        skip = set(deactivate_policy_ids)
        rows = session.scalars(select(SecurityPolicy).where(SecurityPolicy.is_active.is_(True)))
        policies = [PolicyView.from_row(r) for r in rows if r.id not in skip] + list(extra_policies)
        return cls(assets, relationships, policies, PolicyEngine(policies))

    # ---- edges ---------------------------------------------------------------------------

    def edges(self) -> list[Edge]:
        if self._edges is not None:
            return self._edges
        rel_index: dict[tuple[str, str, str], NetworkRelationship] = {}
        for rel in self.relationships:
            if rel.relationship_type is RelationshipType.L2_UPLINK:
                continue
            key = (rel.source_asset_id, rel.destination_asset_id, rel.service)
            # Prefer the baseline relationship when both exist.
            if key not in rel_index or rel.origin is RelationshipOrigin.BASELINE:
                rel_index[key] = rel
        candidates: set[tuple[str, str, str]] = set(rel_index)
        for policy in self.policies:
            if (
                policy.policy_type is not PolicyType.NETWORK_FLOW
                or policy.effect is not PolicyEffect.ALLOW
            ):
                continue
            for src in self._expand(policy.source_asset_id, policy.source_zone_id):
                for dst in self._expand(policy.destination_asset_id, policy.destination_zone_id):
                    if src != dst:
                        candidates.add((src, dst, policy.service_or_action))
        edges: list[Edge] = []
        for src, dst, service in sorted(candidates):
            evaluation = self.engine.evaluate(
                PolicyType.NETWORK_FLOW,
                endpoint_for_asset(self.assets[src]),
                endpoint_for_asset(self.assets[dst]),
                service,
            )
            rel = rel_index.get((src, dst, service))
            edges.append(
                Edge(
                    source=src,
                    destination=dst,
                    service=service,
                    outcome=evaluation.outcome,
                    matched_policy_id=evaluation.matched_policy_id,
                    reason=evaluation.reason,
                    relationship_id=rel.id if rel else None,
                    origin=rel.origin.value if rel else "POLICY_ONLY",
                    observed=bool(rel and rel.last_seen_at is not None),
                )
            )
        self._edges = edges
        return edges

    def _expand(self, asset_id: str | None, zone_id: str | None) -> list[str]:
        if asset_id is not None:
            return [asset_id] if asset_id in self.assets else []
        if zone_id is not None:
            return [a.id for a in self.assets.values() if a.network_zone_id == zone_id]
        return list(self.assets)

    def status_of(self, source: str, destination: str, service: str) -> DecisionOutcome:
        evaluation = self.engine.evaluate(
            PolicyType.NETWORK_FLOW,
            endpoint_for_asset(self.assets.get(source), source),
            endpoint_for_asset(self.assets.get(destination), destination),
            service,
        )
        return evaluation.outcome

    def adjacency(self) -> dict[str, list[Edge]]:
        adj: dict[str, list[Edge]] = {}
        for edge in self.edges():
            if edge.permitted:
                adj.setdefault(edge.source, []).append(edge)
        return adj


# ---- attack paths -----------------------------------------------------------------------


def attack_paths(
    session: Session, ctx: GraphContext, entry: str, max_depth: int = 3, epoch: int | None = None
) -> dict[str, Any]:
    if entry not in ctx.assets:
        return {"entry_asset_id": entry, "error": "Entry asset is not an active physical asset."}
    adjacency = ctx.adjacency()
    paths: list[list[Edge]] = []

    def dfs(node: str, path: list[Edge], visited: frozenset[str]) -> None:
        for edge in adjacency.get(node, []):
            if edge.destination in visited or len(paths) >= MAX_PATHS:
                continue
            new_path = [*path, edge]
            paths.append(new_path)
            if len(new_path) < max_depth:
                dfs(edge.destination, new_path, visited | {edge.destination})

    dfs(entry, [], frozenset({entry}))

    def classify(path: list[Edge]) -> str:
        if len(path) > 1:
            return "HYPOTHETICAL"
        return "DEMONSTRATED" if path[0].observed else "PERMITTED"

    reachable: dict[str, dict[str, Any]] = {}
    rank = {"DEMONSTRATED": 0, "PERMITTED": 1, "HYPOTHETICAL": 2}
    for path in paths:
        dst = path[-1].destination
        cls = classify(path)
        current = reachable.get(dst)
        if current is None or (len(path), rank[cls]) < (
            current["min_hops"],
            rank[current["classification"]],
        ):
            asset = ctx.assets[dst]
            reachable[dst] = {
                "asset_id": dst,
                "display_name": asset.display_name,
                "network_zone_id": asset.network_zone_id,
                "criticality": asset.criticality.value,
                "min_hops": len(path),
                "classification": cls,
                "via": [e.destination for e in path[:-1]],
                "services": [e.service for e in path],
            }

    blocked_from_entry = [e.as_dict() for e in ctx.edges() if e.source == entry and not e.permitted]
    attempted = []
    if epoch is not None:
        rows = session.scalars(
            select(PolicyDecision)
            .where(
                PolicyDecision.source_asset_id == entry,
                PolicyDecision.policy_type == PolicyType.NETWORK_FLOW,
                PolicyDecision.epoch == epoch,
            )
            .order_by(PolicyDecision.id)
        ).all()
        seen: set[tuple[str, str]] = set()
        for row in rows:
            key = (row.destination_ref, row.service_or_action)
            if key in seen:
                continue
            seen.add(key)
            attempted.append(
                {
                    "destination": row.destination_ref,
                    "service": row.service_or_action,
                    "outcome": row.outcome.value,
                    "matched_policy_id": row.matched_policy_id,
                    "policy_decision_id": row.id,
                    "reason": row.reason,
                }
            )

    entry_asset = ctx.assets[entry]
    entry_area = entry_asset.room.area_zone_id if entry_asset.room else None
    nearby_unreachable = []
    for asset in ctx.assets.values():
        if asset.id == entry or asset.id in reachable:
            continue
        same_area = (
            entry_area is not None
            and asset.room is not None
            and asset.room.area_zone_id == entry_area
        )
        same_segment = asset.network_zone_id == entry_asset.network_zone_id
        if same_area or same_segment:
            nearby_unreachable.append(
                {
                    "asset_id": asset.id,
                    "display_name": asset.display_name,
                    "network_zone_id": asset.network_zone_id,
                    "physically_nearby": same_area,
                    "same_network_segment": same_segment,
                    "why_unreachable": "No permitted flow from the entry asset or any reachable asset.",
                }
            )

    affected = dependents_of(session, set(reachable))
    return {
        "entry_asset_id": entry,
        "max_depth": max_depth,
        "assumptions": [
            "The entry asset is treated as attacker-controlled for analysis; this is hypothetical, not a finding.",
            "Only flows the policy engine evaluates as permitted are traversed; blocked flows are never followed.",
            "Moving beyond the first hop requires compromising the intermediate asset through the permitted "
            "service (not demonstrated by this simulation).",
            "Intra-zone segmentation is assumed to be enforced at the access switches (ACLs/private VLANs).",
        ],
        "paths": [
            {
                "hops": [e.as_dict() for e in p],
                "classification": classify(p),
                "length": len(p),
                "target": p[-1].destination,
            }
            for p in sorted(paths, key=lambda p: (len(p), p[-1].destination))
        ],
        "path_count": len(paths),
        "truncated": len(paths) >= MAX_PATHS,
        "reachable_assets": sorted(
            reachable.values(), key=lambda r: (r["min_hops"], r["asset_id"])
        ),
        "blocked_edges_from_entry": blocked_from_entry,
        "observed_attempts": attempted,
        "nearby_unreachable": sorted(nearby_unreachable, key=lambda r: r["asset_id"]),
        "potentially_affected_dependents": affected,
    }


def dependents_of(session: Session, providers: set[str]) -> list[dict[str, Any]]:
    """Everything that (transitively) relies on any of ``providers``."""
    deps = session.scalars(select(OperationalDependency)).all()
    by_provider: dict[str, list[OperationalDependency]] = {}
    for dep in deps:
        by_provider.setdefault(dep.provider_asset_id, []).append(dep)
    names = {a.id: a.display_name for a in session.scalars(select(Asset))}
    out: dict[str, dict[str, Any]] = {}
    queue = deque((p, [p]) for p in sorted(providers))
    while queue:
        provider, chain = queue.popleft()
        for dep in by_provider.get(provider, []):
            dependent = dep.dependent_asset_id
            if dependent in out or dependent in providers:
                continue
            out[dependent] = {
                "asset_id": dependent,
                "display_name": names.get(dependent, dependent),
                "via_provider": provider,
                "dependency_type": dep.dependency_type.value,
                "criticality": dep.criticality.value,
                "chain": [*chain, dependent],
            }
            queue.append((dependent, [*chain, dependent]))
    return sorted(out.values(), key=lambda d: (len(d["chain"]), d["asset_id"]))


# ---- dependency impact (containment) ---------------------------------------------------------


def dependency_impact(session: Session, ctx: GraphContext, isolated: set[str]) -> dict[str, Any]:
    """Which dependencies a policy state would disrupt, and how that propagates."""
    deps = session.scalars(select(OperationalDependency).order_by(OperationalDependency.id)).all()
    rels = {r.id: r for r in session.scalars(select(NetworkRelationship))}
    assets = {a.id: a for a in session.scalars(select(Asset))}
    disrupted: list[dict[str, Any]] = []
    impaired: dict[str, tuple[Criticality, list[str]]] = {}

    def mark(asset_id: str, crit: Criticality, reason: str) -> bool:
        current = impaired.get(asset_id)
        if current is None or CRITICALITY_RANK[crit] > CRITICALITY_RANK[current[0]]:
            impaired[asset_id] = (crit, [*(current[1] if current else []), reason])
            return True
        if reason not in current[1]:
            current[1].append(reason)
        return False

    for dep in deps:
        reason = None
        if dep.provider_asset_id in isolated:
            reason = f"{dep.provider_asset_id} is isolated"
        elif dep.carried_by_relationship_id is not None:
            rel = rels.get(dep.carried_by_relationship_id)
            if (
                rel is not None
                and ctx.status_of(rel.source_asset_id, rel.destination_asset_id, rel.service)
                is DecisionOutcome.BLOCKED
            ):
                reason = f"carrying flow {rel.source_asset_id} -> {rel.destination_asset_id} ({rel.service}) is blocked"
        if reason:
            disrupted.append(
                {
                    "dependent_asset_id": dep.dependent_asset_id,
                    "provider_asset_id": dep.provider_asset_id,
                    "dependency_type": dep.dependency_type.value,
                    "criticality": dep.criticality.value,
                    "description": dep.description,
                    "reason": reason,
                }
            )
            mark(
                dep.dependent_asset_id,
                dep.criticality,
                f"{dep.dependency_type.value} on {dep.provider_asset_id}: {reason}",
            )

    # Propagate only HIGH/CRITICAL impairments: a dependent of a seriously impaired provider is
    # impaired at the dependency's own criticality. Lower-criticality disruptions are listed
    # above but not cascaded, because the model does not know whether the lost function (for
    # example central configuration management) is the one the dependent relies on.
    changed = True
    while changed:
        changed = False
        for dep in deps:
            provider_state = impaired.get(dep.provider_asset_id)
            if provider_state is None:
                continue
            if CRITICALITY_RANK[provider_state[0]] < CRITICALITY_RANK[Criticality.HIGH]:
                continue
            if mark(
                dep.dependent_asset_id,
                dep.criticality,
                f"depends on impaired {dep.provider_asset_id}",
            ):
                changed = True

    services = []
    for asset_id, asset in sorted(assets.items()):
        if not asset.is_logical:
            continue
        state = impaired.get(asset_id)
        if state is None:
            status = "UNAFFECTED"
        elif CRITICALITY_RANK[state[0]] >= CRITICALITY_RANK[Criticality.HIGH]:
            status = "IMPAIRED"
        else:
            status = "DEGRADED"
        services.append(
            {
                "asset_id": asset_id,
                "display_name": asset.display_name,
                "status": status,
                "reasons": state[1] if state else [],
            }
        )
    return {
        "disrupted_dependencies": disrupted,
        "services": services,
        "impaired_assets": [
            {"asset_id": a, "level": c.value, "reasons": r}
            for a, (c, r) in sorted(impaired.items())
            if not assets.get(a) or not assets[a].is_logical
        ],
    }


# ---- whole-graph views ---------------------------------------------------------------------


def network_graph(session: Session) -> dict[str, Any]:
    ctx = GraphContext.load(session)
    nodes = [
        {
            "id": a.id,
            "display_name": a.display_name,
            "asset_kind": a.asset_kind.value,
            "network_zone_id": a.network_zone_id,
            "room_id": a.room_id,
            "discovered": a.discovered,
        }
        for a in ctx.assets.values()
    ]
    rel_edges = []
    for rel in ctx.relationships:
        if rel.relationship_type is RelationshipType.L2_UPLINK:
            status, policy_id, reason = (
                "TOPOLOGY",
                None,
                "Layer-2 attachment only; not a permission.",
            )
        else:
            evaluation = ctx.engine.evaluate(
                PolicyType.NETWORK_FLOW,
                endpoint_for_asset(ctx.assets[rel.source_asset_id]),
                endpoint_for_asset(ctx.assets[rel.destination_asset_id]),
                rel.service,
            )
            status, policy_id, reason = (
                evaluation.outcome.value,
                evaluation.matched_policy_id,
                evaluation.reason,
            )
        src, dst = ctx.assets[rel.source_asset_id], ctx.assets[rel.destination_asset_id]
        rel_edges.append(
            {
                "id": rel.id,
                "source": rel.source_asset_id,
                "destination": rel.destination_asset_id,
                "relationship_type": rel.relationship_type.value,
                "service": rel.service,
                "protocol_label": rel.protocol_label,
                "origin": rel.origin.value,
                "policy_status": status,
                "matched_policy_id": policy_id,
                "policy_reason": reason,
                "crosses_zone_boundary": src.network_zone_id != dst.network_zone_id,
                "last_seen_at": rel.last_seen_at,
                "observation_count": rel.observation_count,
            }
        )
    return {"nodes": nodes, "edges": rel_edges}


def dependency_graph(session: Session) -> dict[str, Any]:
    assets = {a.id: a for a in session.scalars(select(Asset).where(Asset.is_active.is_(True)))}
    deps = session.scalars(select(OperationalDependency).order_by(OperationalDependency.id)).all()
    return {
        "nodes": [
            {
                "id": a.id,
                "display_name": a.display_name,
                "is_logical": a.is_logical,
                "asset_kind": a.asset_kind.value,
                "criticality": a.criticality.value,
            }
            for a in assets.values()
        ],
        "edges": [
            {
                "id": d.id,
                "dependent": d.dependent_asset_id,
                "provider": d.provider_asset_id,
                "dependency_type": d.dependency_type.value,
                "criticality": d.criticality.value,
                "description": d.description,
                "carried_by_relationship_id": d.carried_by_relationship_id,
            }
            for d in deps
            if d.dependent_asset_id in assets and d.provider_asset_id in assets
        ],
    }
