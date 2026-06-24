"""Single source of truth for the resume Executive Summary instructions.

Both resume prompts (the standalone tool's REWRITE_SYSTEM and the session
builder's RESUME_REWRITE_SYSTEM) import SUMMARY_RULES so the summary logic is
identical everywhere and can be improved in one place.

Design: the summary is a fixed three-sentence machine — Identity / Proof /
Target — taught with two real exemplars. The earlier rule set banned metrics
AND accomplishments, which deleted the load-bearing Proof sentence and forced
the model into "precious" character description. This version makes Proof
mandatory and bans working-style/personality language instead.
"""

SUMMARY_RULES = """SUMMARY RULES — the summary follows a fixed three-sentence architecture: IDENTITY, PROOF, TARGET. This is the load-bearing section, and it fails when it drifts into describing personality instead of positioning value. Follow the architecture exactly.

SENTENCE 1 — IDENTITY. State who the candidate is by function, in implied first person (no name, no pronouns, no throat-clearing). Lead with the professional category, then what they do at their best in concrete, active terms. A short triad of capabilities is allowed ONLY if Sentence 2 proves it.

SENTENCE 2 — PROOF (mandatory, never omit). The single most impressive TRUE thing this person has done, carried by concrete scale, scope, duration, or context that a competitor in the same field could not copy. This is what separates a real summary from a character sketch. Build it around ONE signature arc plus at most one or two concrete scale anchors — keep it to a single readable sentence; do not chain the candidate's entire career into a run-on. Anchor in specifics: years, startup-to-maturity, regulated market, named domains, level of command or scale. Hard numbers (%/$) are NOT required and must never be invented; concrete scale and specificity ARE required. If the source material genuinely lacks a signature arc, write the strongest true proof available from the actual experience — never fall back to personality to fill this sentence.

SENTENCE 3 — TARGET. Name the seniority band, the function(s), and the specific kinds of organizations being pursued. Precise ("senior director to VP roles in X, Y, or Z at [specific org types]"), never vague ("organizations where my range creates leverage"). STOP after the organization types. Never append a clause about how the candidate works, thinks, or what they value (no "...who asks why before how," no "...where outcomes matter over outputs"). The sentence ends at the targets.

VOICE AND BANS:
- Implied first person throughout. No name, no pronouns.
- Convey character ONLY through what the person built or led — never through adjectives about how they think or work. BAN working-style description outright: "asks why before how," "works from data not opinion," "stays close to the customer," "thinks from first principles," and anything like them. If a clause describes temperament rather than function or accomplishment, cut it.
- No nominalized abstractions carrying a sentence ("infrastructure," "ecosystem," "alignment," "transformation," "visibility"). Use verbs; say what the person does.
- No comparisons to other leaders ("unlike most," "rare," "uniquely positioned").
- No em dashes. No cute phrases. Plain, confident, declarative — the way you would describe the candidate to a peer recruiter on the phone.
- Every sentence falsifiable and specific to THIS person. If another professional in the same field could say it verbatim, sharpen it until they couldn't.
- Avoid laundry-list enumerations of skills or domains; one resonant range statement beats a string of five nouns.
- No self-flattering or generic opening adjectives: "driven," "dynamic," "results-oriented," "highly collaborative," "seasoned," "passionate," "proven," "accomplished."
- Ban competency-catalog constructions: "comprehensive expertise in [A, B, C, D]," "excels at [gerund, gerund, gerund]," "operates at the intersection of...". A sentence that only names what the candidate is good at, with no concrete instance behind it, must be cut and replaced with proof.

NUMERIC FIDELITY — non-negotiable: Every figure in the summary (headcounts, store/unit/device counts, dollar amounts, percentages, years, user/beneficiary counts) must appear verbatim in the source materials. Never round up, scale, aggregate, or estimate a number, and never invent one. If a figure in the resume and the transcript disagree, use the more conservative one. If you are not certain a number is supported, describe the scale qualitatively ("enterprise scale," "national footprint") instead of stating a figure.

CONTEXT NOTE: When a session transcript or intake is provided, treat it as coaching material full of self-reflection. Mine it for the PROOF — the signature arc, the scale, the real outcomes — not for personality language. The summary is market-facing positioning, not a character study.

EXEMPLARS — match this register and architecture. Different fields, identical DNA (Identity / Proof / Target):

EXAMPLE A:
Health plan operations and compliance executive with a track record of building trust, creating structure, and leading through complexity when the stakes are high. Built and sustained the compliance and operational backbone that carried a commercial HMO from startup to maturity over eleven years and through repeated leadership transitions, in one of the most heavily regulated markets in the country. Targeting senior director to VP roles in health plan operations, compliance leadership, or health plan strategy at integrated delivery systems, regional and/or national health plans, and mission-driven healthcare organizations.

EXAMPLE B:
Decision-intelligence leader who turns fragmented, noisy inputs into clear choices that executives and commanders can act on and defend. Carries unusual technical depth, from rocket propulsion engineering to marketing mix modeling, paired with command-level leadership of intelligence and product teams at the largest civilian and military scale. Targets senior strategy and insights roles where analytical rigor and battle-tested leadership under ambiguity are valued at once.

ANTI-EXEMPLAR — NEVER write like this. This is generic boilerplate any executive in the field could claim; it is all category labels and self-praise with zero proof:
"A driven, highly collaborative senior partnership and marketing executive with comprehensive global and domestic expertise in strategy development, P&L ownership, enterprise partnerships, budget management, vendor relations, and CLV performance measurement. Leads fully integrated, customer-first commercial functions across loyalty, financial services, paid media, CRM, lifecycle, and direct channels at scale. Operates at the intersection of marketing strategy, martech, and commercial outcomes across matrixed organizations within hospitality and retail. Excels at driving customer lifetime value growth, optimizing large-scale media investments, and building high-performing global teams."
Why it fails: opens with self-flattering adjectives; stacks competency laundry lists; names categories the candidate operates in but never one concrete thing they actually did; no scale, no signature arc, nothing falsifiable. If a draft resembles this, it is labels instead of proof — discard it and rebuild from the Proof sentence."""
