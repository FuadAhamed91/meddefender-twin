# Demo walkthrough

A guided tour of MedDefender Twin, from a quiet baseline through each attack scenario to
containment, recovery and audit. Everything shown is synthetic: the "hospital", its devices,
its traffic and every attack are simulated, and nothing connects to real clinical systems.

Start the stack first ([README, Quick start](../README.md#quick-start-docker-compose)) and
sign in as **secadmin**. Some steps note what a **viewer** or **operator** would see instead.

## 1. The baseline

The **Twin** page opens with a short camera glide onto the floor.

- **Left panel.** *Navigate* jumps to a zone (ICU, Imaging suite, IT / Server room, Building
  management) or back to the whole floor. *Overlays* switches the view style
  (**Holographic** security view or **Realistic** architectural view) and the network-flow
  and zone overlays; *Legend* explains the colours. Machines without GPU acceleration get
  reduced effects automatically. *Assets* lists every asset with its trust state; assets with
  open incidents come first.
- **The canvas.** Devices are small dots until they need attention: a device that is
  selected, alerting, or in an abnormal trust or containment state gets a labelled chip.
  The top right counts this session's message decisions (accepted · held · rejected). The
  bottom left confirms that the twin mapping is verified, meaning every backend asset was
  found in the Blender model by its ID.
- **Right panel.** *Situation* lists open incidents and assets needing attention.

Leave it running for a minute. The telemetry generator sends signed messages from the
simulated devices, and **Dashboard** shows message decisions per minute, trust states, why
messages were rejected or held, and alerts by classification. Each chart has a table view.

Select any device, from the list, its marker or the 3D model. The selected device gets an
outline and a light pillar, unrelated flows dim, and the inspector shows backend state:

- **Overview**: identity, criticality, zone and room (network zone and physical room are
  deliberately different attributes).
- **State**: reported, trusted and predicted values side by side.
- **Security**: credential *metadata* (version and fingerprint; keys are never stored or
  shown), inbound and outbound permissions, and the commands this device accepts.
- **Network** and **Dependencies**: communication paths with their current policy decision,
  and what this asset relies on or is relied on by. These are separate graphs.
- **History**: recent messages with per-check results, and the asset's audit trail.

## 2. Scenario A: replayed medical telemetry

**Scenarios → Replayed medical telemetry → Run.** An on-path attacker re-sends a genuine,
signed bedside-monitor message, then replays an older capture.

What to look at in the result:

- The steps show the real pipeline checks. The HMAC *passes* (the message is authentic);
  the sequence, nonce and, for the old capture, freshness checks reject it.
- **Expectations, evaluated against persisted state**: trusted state unchanged, audit event
  and incident recorded, device trust unchanged. A replay is a protocol violation by the
  sender of the copy; the monitor itself did nothing wrong.
- **View in twin** focuses the affected assets. The incident appears under **Incidents**.

## 3. Scenario B: unauthorized device command

The imaging workstation authenticates correctly but asks the command broker to change a
bedside monitor's alarm limits.

- The command is denied by default-deny command policy, with the matched rule and reason.
- The monitor's simulated state is unchanged, and the requesting identity becomes
  **Suspicious**, which removes its command privileges through the trust gate.
- A positive control shows that an authorized source succeeds.

Under **Policies**, *Policy dry run* reproduces the decision. It explains the matched rule
and any shadowed rules without changing anything.

## 4. Scenario C: rogue device registration

An unknown endpoint appears on the ICU segment, tries to talk to clinical systems, sends
telemetry under an unregistered ID, impersonates ICU-MONITOR-02 without its key and asks to
be enrolled.

- The endpoint shows up as **Unregistered** (violet chip, light pillar and wireframe placeholder in the twin),
  all its flows are blocked by default deny, and its messages are rejected.
- The impersonated monitor is **not** penalised: failed authentication never counts against
  the claimed identity.
- The enrollment request stays pending. Approval is an explicit security-admin decision
  (`/api/v1/devices/enrollments`, see the API docs at `/api/docs`).

## 5. Scenario D: compromised gateway and lateral movement

The ICU central monitoring gateway starts reaching outside its permitted communication
policy.

- Blocked flows appear as red dashed arcs. The gateway becomes **Suspicious**: it gets a
  labelled chip and an amber light pillar. An incident opens.
- Select the gateway and choose **Attack paths from here**. Only flows the policy engine
  permits are traversed. Each hop is labelled *Demonstrated* (observed and permitted),
  *Permitted* (allowed, not observed) or *Hypothetical* (requires compromising an
  intermediate asset). Blocked attempts are listed separately, and assets that are
  physically nearby but unreachable are marked as such.

## 6. Scenario E: telemetry manipulation

An environment sensor reports values that conflict with its schema, its limits and the
deterministic room model.

- Schema and limit violations are **rejected**. A plausible-but-wrong value that disagrees
  with the model is **held**: authentic, yet not trusted.
- In the inspector's **State** tab, reported, trusted and predicted values diverge, and only
  trusted values drive the twin. The alert is a *suspected anomaly* with a confidence note
  (sensor fault, unmodelled heat sources and model error are possible explanations).

## 7. Scenario F and the incident workflow: containment, recovery, replay

Open the gateway incident from scenario D (**Incidents**, or the link in the run result). The
lifecycle runs Detected → Investigating → Containment proposed → Contained → Recovery →
Resolved, and the backend rejects any transition outside it.

1. **Start investigation**, then go to the **Containment** tab and **Generate plans**
   (this moves the incident to *Containment proposed*). Four options are compared without
   changing anything: isolate the asset, restrict it to its required flows, block the
   zone's egress, or revoke its credentials. For each you see attack paths before and after,
   reachable and high-value assets, the flows the plan blocks, dependencies disrupted and
   services impaired, plus the approval it needs.
2. **Preview on twin** draws a plan's blocked flows on the floor so the impact is visible
   before deciding.
3. **Apply plan** asks for a justification, which is recorded in the audit trail. A plan
   that impairs a clinical or operational service requires a security admin; an operator can
   apply only the low-impact ones. After applying, the device shows *Isolated* or
   *Restricted*, and its room turns red in the twin.
4. **Begin recovery**, then use the **Recovery** tab: rotate the device credentials (new key
   version), release the containment policies (deactivated and kept for evidence, never
   deleted), and restore trusted state to the last known-good observation.
5. **Resolve** with a note. An incident that turns out to need no containment can instead be
   resolved straight from *Investigating* as false positive, benign, no action required or
   accepted risk.
6. The **Replay** tab steps through the incident as it was recorded, highlighting the
   assets involved on the twin at each step.

Scenario F runs the plan comparison from the scenario console as well. It fails its
precondition honestly when no gateway incident exists yet, so run it after D.

## 8. Audit and reset

- **Audit** lists every decision with actor, action, target, decision and reason. **Verify
  hash chain** (operator and above) recomputes the SHA-256 chain. There are no edit or delete
  endpoints, and a database trigger rejects updates and deletes.
- **Reset baseline** (security admin, on the Scenarios page) starts a new simulation epoch.
  Audit history and incidents from earlier epochs are kept, and replay protection is *not*
  reset, so previously captured messages stay unusable.

## 9. Roles

Sign in as **viewer**: everything is visible, but scenario runs, incident transitions,
containment and recovery are disabled in the UI and refused by the API, and each refused
attempt is audited. **operator** can run scenarios and handle incidents but cannot reset the
simulation, manage identities or policies, or apply high-impact containment.
