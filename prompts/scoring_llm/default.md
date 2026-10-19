---
system: |
  You are a strict, objective job-match decision model. Score the job against the candidate on five atomic dimensions. Reply with a single JSON object and nothing else.
---
Candidate:
- Seniority: {{seniority}} (wanted contract: {{contract_type}})
- Core skills: {{core_skills}}
- Preferred tools: {{tools}}
- Primary location: {{primary_location}}

Dimension guidance:
- core_score: how well the required core skills match the candidate's core stack (0 none, 1 primary requirement).
- tools_score: how many of the candidate's preferred tools the job covers.
- contract_score: how well contract type and seniority fit the preference.
- pay_score: 0.5 if pay is missing/unstated, 0.0-0.4 clearly below market, 0.5-0.7 plausible, 0.8-1.0 at/above target.
- pay_missing: true when compensation is not stated or unclear.
- location_bucket: "primary" | "remote" | "hybrid" | "elsewhere" | "unknown".
- confidence: 0.0-1.0, how certain you are of this evaluation.
- summary_reason: one concise sentence.

Job posting:
Title: {{title}}
Company: {{company}}
Declared location: {{location}}
Declared salary: {{salary}}
Description:
{{description}}

Return JSON exactly like:
{"core_score": 0.0, "tools_score": 0.0, "contract_score": 0.0, "pay_score": 0.5, "pay_missing": true, "location_bucket": "unknown", "confidence": 0.8, "summary_reason": ""}
