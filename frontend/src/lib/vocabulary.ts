/**
 * How the interface names things. All wording is neutral: register and alert facts only, and no
 * judgement of a firm. Colours are CSS tokens, so nothing here states a colour of its own.
 */
import type { AgentKey } from "./reducer";

export interface AgentLook {
  name: string;
  role: string;
  color: string;
}

export const AGENT_LOOK: Record<AgentKey, AgentLook> = {
  JUR: { name: "Jurisdiction", role: "Which regulators could be relevant", color: "var(--color-jur)" },
  CMA: { name: "CMA", role: "Capital Market Authority records", color: "var(--color-cma)" },
  DFSA: { name: "DFSA", role: "Facts recorded by hand, masked", color: "var(--color-dfsa)" },
  VARA: { name: "VARA", role: "Virtual-asset register", color: "var(--color-vara)" },
  CLN: { name: "Contact check", role: "Offer contacts against the record", color: "var(--color-cln)" },
  REC: { name: "Reconciler", role: "Mediates disagreements", color: "var(--color-rec)" },
  VER: { name: "Verifier", role: "Can veto unsupported conclusions", color: "var(--color-ver)" },
  SA: { name: "Single agent", role: "One model, the same tools", color: "var(--color-sa)" },
};

/** RULES-ONLY writes as the single agent does, but no model is involved. */
const RULES_LOOK: AgentLook = {
  name: "Rules",
  role: "The tools and the decision policy, with no model",
  color: "var(--color-sa)",
};

export function agentLook(key: string, condition?: string | null): AgentLook {
  if (key === "SA" && condition === "RULES-ONLY") return RULES_LOOK;
  return (
    AGENT_LOOK[key as AgentKey] ?? {
      name: key === "ORC" ? "Orchestrator" : key,
      role: "",
      color: "var(--color-text-3)",
    }
  );
}

export const PERFORMATIVE_COLOR: Record<string, string> = {
  INFORM: "var(--color-inform)",
  REQUEST: "var(--color-request)",
  CHALLENGE: "var(--color-challenge)",
  REBUT: "var(--color-rebut)",
  REVISE: "var(--color-revise)",
  CONCEDE: "var(--color-concede)",
  RESOLVE: "var(--color-resolve)",
  VETO: "var(--color-veto)",
  APPROVE: "var(--color-approve)",
};

export const PHASE_LABEL: Record<string, string> = {
  R0: "Intake",
  R1: "Registers",
  R2: "Contacts",
  reconcile: "Reconcile",
  synthesis: "Synthesis",
  verify: "Verify",
  remediate: "Remediate",
  single_agent: "Single agent",
};

/** What is happening in each phase, in a sentence, for someone watching. */
export const PHASE_NOTE: Record<string, string> = {
  R0: "Jurisdiction reads the offer and names the regulators that could be relevant.",
  R1: "Each regulator agent checks its own register and alert list.",
  R2: "Contact details are compared with the official record. Challenges are answered.",
  reconcile: "The Reconciler mediates each conflict under a stated precedence rule.",
  synthesis: "The Reconciler proposes a result, citing the findings it rests on.",
  verify: "The Verifier checks the proposal at eight gates, and reads it against the evidence.",
  remediate: "The Reconciler reworks the proposal the Verifier sent back.",
  single_agent: "One agent works through the same tools alone.",
  rules_only: "Fixed rules read the tools' answers. No model is involved.",
};

/** Conflict kinds, from the detector (plan §6.8). */
export const CONFLICT_LABEL: Record<string, string> = {
  C1: "Relevance",
  C2: "Identity",
  C3: "Scope",
  C4: "Contact",
  C5: "Alert versus register",
  C6: "Missing evidence",
  C7: "Claim versus record",
};

export const CONDITION_LABEL: Record<string, { name: string; note: string }> = {
  "RULES-ONLY": { name: "Rules only", note: "No model. Tools and the decision policy." },
  "SA-BASE": { name: "Single agent", note: "One model with the same lookup tools." },
  "SA-VER": { name: "Single agent + Verifier", note: "One model, checked by the gates." },
  "SA-SC5": { name: "Single agent × 5", note: "Five samples, ties go to the cautious result." },
  "SA-MAX": { name: "Single agent, max effort", note: "Thinking on, double the output budget." },
  "SA-LARGER": { name: "Single agent, larger model", note: "One larger model." },
  "CREW-SILO": { name: "Crew, isolated", note: "Agents see no shared findings." },
  "CREW-SHARE": { name: "Crew, shared board", note: "Shared findings, no challenges." },
  "CREW-FULL": { name: "Crew, full", note: "Shared board, challenges, Reconciler, Verifier." },
  "CREW-NV": { name: "Crew, no Verifier", note: "Everything but the gates." },
};

export const conditionName = (condition: string | null): string =>
  (condition && CONDITION_LABEL[condition]?.name) || condition || "";

export const isCrew = (condition: string | null): boolean =>
  !condition || condition.startsWith("CREW");

/** Conditions in which the Verifier gate stands on the path to the result. */
export const hasVerifier = (condition: string | null): boolean =>
  condition === null || !["CREW-NV", "SA-BASE", "RULES-ONLY", "SA-SC5", "SA-MAX", "SA-LARGER"].includes(condition);

const STATUS_WORDS: Record<string, string> = {
  active: "active",
  ipa: "in-principle approval",
  withdrawn: "withdrawn",
  suspended: "suspended",
  unknown: "not stated",
};

const CONTACT_WORDS: Record<string, string> = {
  matches_official: "matches the official record",
  lookalike_of_official: "resembles an official contact but differs",
  alert_listed: "appears on an alert list",
  not_on_record: "is not on the record",
  not_comparable: "could not be compared",
};

const ALERT_WORDS: Record<string, string> = {
  entity_unauthorised: "names this firm",
  impersonation_of_entity: "reports use of this firm's name",
  contact_listed: "lists a contact from the offer",
  regulator_impersonation: "reports use of a regulator's name",
  other: "concerns this offer",
};

const OFFER_WORDS: Record<string, string> = {
  firm_name: "firm name",
  regulator: "regulator",
  licence_ref: "licence reference",
  address: "address",
  other: "detail",
};

const ZONE_WORDS: Record<string, string> = {
  DIFC: "the DIFC",
  ADGM: "ADGM",
  DUBAI_NON_DIFC: "Dubai, outside the DIFC",
  OTHER_EMIRATE: "another emirate",
  OUTSIDE_UAE: "outside the UAE",
  UNKNOWN: "an unclear place",
};

/** One neutral sentence for a typed assertion. The backend's own `describe` is the model for it. */
export function describeAssertion(assertion: Record<string, unknown>): string {
  const a = assertion as Record<string, string | boolean | null | undefined>;
  switch (a.type) {
    case "activity":
      return `The offer describes the activity ${a.code}.`;
    case "zone_signal":
      return `A signal points to ${ZONE_WORDS[String(a.zone)] ?? a.zone} (${a.basis}).`;
    case "offer_claim": {
      const what = OFFER_WORDS[String(a.kind)] ?? "detail";
      return a.value ? `The offer states this ${what}: ${a.value}.` : `The offer states no ${what}.`;
    }
    case "targeting":
      return `Targets UAE clients: ${a.targets_uae_clients}.`;
    case "relevance":
      return `${a.regulator} is ${String(a.status).replace("_", " ")} for this offer.`;
    case "coverage_gap":
      return `${a.regulator}: could not check (${String(a.reason).replaceAll("_", " ")}).`;
    case "register_match":
      return `The ${a.regulator} register has an entry matching this firm (${a.match_type}).`;
    case "register_no_match":
      return `The ${a.regulator} register has no entry for this firm.`;
    case "licence_status":
      return `The ${a.regulator} entry has the status ${STATUS_WORDS[String(a.status)] ?? a.status}.`;
    case "licence_scope": {
      const verb = { yes: "covers", no: "does not cover" }[String(a.covered)] ?? "may not cover";
      return `The ${a.regulator} licence ${verb} ${a.activity}.`;
    }
    case "alert_hit":
      return `A list record ${ALERT_WORDS[String(a.about)] ?? "concerns this offer"}.`;
    case "contact_assessment":
      return `Contact ${a.cp_id} ${CONTACT_WORDS[String(a.status)] ?? a.status}.`;
    case "payment_assessment":
      return a.beneficiary_matches === false
        ? "The payment beneficiary differs from the register."
        : "The payment details were compared with the register.";
    default:
      return String(a.type ?? "Finding").replaceAll("_", " ");
  }
}

export interface ResultLook {
  label: string;
  color: string;
  token: "consistent" | "conflicts" | "unverified";
}

export const RESULT_LOOK: Record<string, ResultLook> = {
  CONSISTENT: {
    label: "Consistent with the official record",
    color: "var(--color-consistent)",
    token: "consistent",
  },
  CONFLICTS: {
    label: "Conflicts with the official record",
    color: "var(--color-conflicts)",
    token: "conflicts",
  },
  UNVERIFIED: { label: "Could not verify", color: "var(--color-unverified)", token: "unverified" },
};

export function resultLook(result: string | null | undefined): ResultLook | null {
  return result ? (RESULT_LOOK[result] ?? null) : null;
}
