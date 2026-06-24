"""Single source of truth for experience-bullet instructions.

Distilled from docs/resume_bullets_rubric.md (the human-readable standard) into
a prompt-ready block. Imported by both resume prompts so bullet guidance is
identical across the standalone tool and the session builder, and improves in
one place. Keep this in sync with the rubric when the rubric changes.
"""

BULLET_RULES = """BULLET RULES — every experience bullet is evidence that something changed because the candidate showed up. Write for the hiring manager who can say yes, but keep it legible to a non-expert recruiter/ATS screener.

THE TEST: every bullet must answer "so what?" A qualitative outcome a hiring manager would care about passes. A hard metric is welcome when it is real and defensible, but it is NEVER required and must never be invented or inflated.

SHAPE — Context / Action / Result, compressed: the situation or stakes, what the candidate specifically did (strong past-tense verb), and what changed. The result often leads.

RULES:
- Lead with a strong past-tense verb. Never open with "Responsible for," "Tasked with," "Duties included," "Helped," "Assisted," "Worked on," "Supported," or "Participated in."
- End on a result. If a bullet states only what was assigned or maintained, rewrite it until it answers "so what?" — or cut it.
- Quantify only what is real and defensible; never fabricate or inflate a figure. A true qualitative result beats a fake metric.
- One idea per bullet. No "and also" stacking.
- Credit the candidate's actual scope honestly — not "we" (which erases them), not inflation (which lies).
- Front-load the payload: the outcome or strongest element first; context trails.
- Specifics over abstractions. Name the system, scale, or domain. Kill buzzword filler (synergy, transformation, leverage, ecosystem).
- Keep ONE concrete layer of domain detail for credibility, wrapped in an outcome a non-expert can grasp. Do not bury the signal in acronym soup, and do not strip it to nothing.
- Cut table-stakes duties everyone in the role obviously performs.
- Order bullets within each role by impact: the biggest, most thesis-relevant bullet first.
- Cut any bullet that does not serve the positioning thesis, however well written.
- One to two lines each. Vary the opening verb — never start three bullets the same way.

GOOD vs BAD:
- BAD: Responsible for managing vendor relationships.
  GOOD: Renegotiated 12 vendor contracts, cutting annual spend by $1.4M.
- BAD: Built a dashboard tracking inventory across stores.
  GOOD: Built the inventory dashboard the operations team now runs every weekly review from, after it surfaced $800K in mislabeled stock.
- BAD: Helped the team launch the new platform.
  GOOD: Owned the authentication layer for the platform launch, integrating SSO across 70,000 endpoints.

NEVER produce: duty lists, responsibility soup, buzzword bullets, "Assisted/Helped" self-erasure, run-on "and also" bullets, or big numbers with no meaning or defensibility."""
