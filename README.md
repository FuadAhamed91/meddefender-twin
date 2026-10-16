# MedDefender Twin

**A healthcare IoT cybersecurity simulation platform with a live 3D digital twin.**

> ⚠️ **Simulation only.** Every hospital asset, network flow, telemetry value, clinical
> workflow and attack in this project is synthetic. It does not connect to or control real
> clinical infrastructure or medical devices, and it makes no claim of clinical safety,
> regulatory compliance or production readiness.

MedDefender Twin simulates a small hospital (ICU, imaging suite, server room and building
management) and runs a real backend security pipeline over signed device messages:
identity, HMAC integrity, replay protection, policy enforcement and deterministic
detection rules. Its 3D digital twin is a projection of that backend state: it shows
where an affected asset is, what it can reach under current policy, what depends on it,
and what a containment decision would disrupt.

🚧 **Work in progress.** Building incrementally; see [docs/PLAN.md](docs/PLAN.md).

## Documentation

* [Architecture](docs/ARCHITECTURE.md)
* [Threat model](docs/THREAT_MODEL.md)
* [Implementation and test plan](docs/PLAN.md)

## License

MIT. See [LICENSE](LICENSE).
