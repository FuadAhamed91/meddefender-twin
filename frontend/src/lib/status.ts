import {
  Ban,
  CircleAlert,
  CircleCheck,
  CircleDashed,
  CircleHelp,
  CirclePause,
  CircleX,
  Eye,
  Cable,
  Info,
  KeyRound,
  Lock,
  OctagonAlert,
  Search,
  Shield,
  ShieldAlert,
  ShieldBan,
  ShieldCheck,
  ShieldOff,
  ShieldQuestion,
  TriangleAlert,
  Undo2,
  Wrench,
  WifiOff,
  ArrowRightLeft,
  ScanLine,
  Radar,
  type LucideIcon,
} from "lucide-react";
import type {
  AlertClassification,
  ContainmentState,
  Decision,
  IncidentStatus,
  PolicyOutcome,
  Severity,
  TrustState,
} from "../api/types";

/** Every status pairs a color with an icon and a text label (never color alone). */
export interface StatusStyle {
  label: string;
  color: string; // CSS color (also used by the 3D scene)
  icon: LucideIcon;
  description: string;
}

export const TRUST: Record<TrustState, StatusStyle> = {
  AUTHENTICATED: { label: "Authenticated", color: "#34d399", icon: ShieldCheck, description: "Proved key possession with a fresh, valid message." },
  REGISTERED: { label: "Registered", color: "#9aabc2", icon: Shield, description: "Has a credential but has not authenticated yet." },
  SUSPICIOUS: { label: "Suspicious", color: "#f5b945", icon: ShieldAlert, description: "Authenticated, but behaved outside policy or failed validation. Commands are refused." },
  QUARANTINED: { label: "Quarantined", color: "#f04452", icon: ShieldBan, description: "Contained: its messages are refused." },
  REVOKED: { label: "Revoked", color: "#d0647a", icon: ShieldOff, description: "Credential revoked; must be re-provisioned." },
  OFFLINE: { label: "Offline", color: "#64748b", icon: WifiOff, description: "No authentic message recently." },
  UNREGISTERED: { label: "Unregistered", color: "#c084fc", icon: ShieldQuestion, description: "Observed on the network but not in the identity registry. Never trusted." },
};

export const NO_IDENTITY: StatusStyle = {
  label: "No device identity",
  color: "#64748b",
  icon: Cable,
  description: "Not a messaging endpoint in this model (infrastructure or logical service).",
};

export const SEVERITY: Record<Severity, StatusStyle> = {
  CRITICAL: { label: "Critical", color: "#f04452", icon: OctagonAlert, description: "Critical severity" },
  HIGH: { label: "High", color: "#f2803a", icon: TriangleAlert, description: "High severity" },
  MEDIUM: { label: "Medium", color: "#f5b945", icon: CircleAlert, description: "Medium severity" },
  LOW: { label: "Low", color: "#5aa9f0", icon: Info, description: "Low severity" },
  INFO: { label: "Info", color: "#9aabc2", icon: Info, description: "Informational" },
};

export const DECISION: Record<Decision, StatusStyle> = {
  ACCEPTED: { label: "Accepted", color: "#34d399", icon: CircleCheck, description: "Passed every check; trusted state updated." },
  HELD: { label: "Held", color: "#f5b945", icon: CirclePause, description: "Authentic but disagrees with the model; held for review, not trusted." },
  REJECTED: { label: "Rejected", color: "#f04452", icon: CircleX, description: "Failed a check; trusted state unchanged." },
};

export const OUTCOME: Record<PolicyOutcome, StatusStyle> = {
  PERMITTED: { label: "Permitted", color: "#22c3d6", icon: ArrowRightLeft, description: "Allowed by an explicit policy." },
  BLOCKED: { label: "Blocked", color: "#f04452", icon: Ban, description: "Denied by an enforced policy (or default deny)." },
  ALLOWED_MONITOR_ONLY: { label: "Monitor only", color: "#f5b945", icon: Eye, description: "A deny policy matched but is in monitor mode; traffic was not blocked." },
  TOPOLOGY: { label: "Topology", color: "#64748b", icon: Cable, description: "Physical/L2 attachment only. Not a permission." },
};

export const CLASSIFICATION: Record<AlertClassification, StatusStyle & { short: string }> = {
  CONFIRMED_POLICY_VIOLATION: { short: "Confirmed", label: "Confirmed policy violation", color: "#f04452", icon: Ban, description: "Evaluated against an explicit policy and denied." },
  PROTOCOL_VIOLATION: { short: "Protocol", label: "Protocol violation", color: "#f2803a", icon: OctagonAlert, description: "Violated the message protocol (replay, sequence, freshness)." },
  VALIDATION_FAILURE: { short: "Validation", label: "Validation failure", color: "#f5b945", icon: CircleX, description: "Failed schema or physical-limit checks." },
  AUTHENTICATION_FAILURE: { short: "Auth", label: "Authentication failure", color: "#c084fc", icon: KeyRound, description: "Could not be authenticated." },
  SUSPECTED_ANOMALY: { short: "Suspected", label: "Suspected anomaly", color: "#5aa9f0", icon: CircleHelp, description: "Deviates from a model or baseline; benign explanations exist." },
};

export const CONTAINMENT: Record<ContainmentState, StatusStyle> = {
  NONE: { label: "Not contained", color: "#64748b", icon: CircleDashed, description: "No containment applied." },
  RESTRICTED: { label: "Restricted", color: "#f5b945", icon: Lock, description: "Containment policies restrict some of its flows." },
  ISOLATED: { label: "Isolated", color: "#f04452", icon: ShieldBan, description: "All flows to and from the asset are blocked." },
};

export const INCIDENT_STATUS: Record<IncidentStatus, StatusStyle> = {
  DETECTED: { label: "Detected", color: "#f2803a", icon: Radar, description: "Opened by a detection rule." },
  INVESTIGATING: { label: "Investigating", color: "#5aa9f0", icon: Search, description: "Under analysis." },
  CONTAINMENT_PROPOSED: { label: "Containment proposed", color: "#c084fc", icon: ScanLine, description: "Containment options generated and awaiting a decision." },
  CONTAINED: { label: "Contained", color: "#f5b945", icon: Lock, description: "A containment plan was applied." },
  RECOVERY: { label: "Recovery", color: "#22c3d6", icon: Wrench, description: "Recovery actions in progress." },
  RESOLVED: { label: "Resolved", color: "#34d399", icon: CircleCheck, description: "Closed; evidence retained." },
};

export const INCIDENT_FLOW: IncidentStatus[] = ["DETECTED", "INVESTIGATING", "CONTAINMENT_PROPOSED", "CONTAINED", "RECOVERY", "RESOLVED"];

export const CHECK_STATUS: Record<string, StatusStyle> = {
  PASS: { label: "Pass", color: "#34d399", icon: CircleCheck, description: "Check passed" },
  FAIL: { label: "Fail", color: "#f04452", icon: CircleX, description: "Check failed" },
  WARN: { label: "Warn", color: "#f5b945", icon: CircleAlert, description: "Check raised a warning" },
  SKIPPED: { label: "Skipped", color: "#64748b", icon: CircleDashed, description: "Not evaluated" },
  NOT_APPLICABLE: { label: "N/A", color: "#64748b", icon: CircleDashed, description: "Not applicable" },
  INFO: { label: "Info", color: "#9aabc2", icon: Info, description: "Information" },
};

export const PATH_CLASS: Record<string, StatusStyle> = {
  DEMONSTRATED: { label: "Demonstrated", color: "#f2803a", icon: Eye, description: "Permitted and actually observed during the simulation." },
  PERMITTED: { label: "Permitted", color: "#f5b945", icon: ArrowRightLeft, description: "Allowed by policy but not observed." },
  HYPOTHETICAL: { label: "Hypothetical", color: "#9aabc2", icon: CircleHelp, description: "Requires compromising an intermediate asset (not demonstrated)." },
};

export const RECOVERY_ICON = Undo2;

export function trustStyle(state: TrustState | null | undefined): StatusStyle {
  return state ? TRUST[state] : NO_IDENTITY;
}
