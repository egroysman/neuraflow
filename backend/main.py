Return valid JSON only, but make the "answer" field read like a polished human finance summary.

The answer should be:
- plain English
- no JSON formatting inside the answer
- no code blocks
- no raw object keys
- concise but useful
- written like a finance leader explaining the result

Use this exact JSON shape:

{
  "confidence": 0.0,
  "is_ambiguous": false,
  "interpretations": [],
  "restate": "",
  "clarifying_question": "",
  "answer": "Write the actual human-readable answer here.",
  "assumptions": ""
}