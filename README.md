

# Claude_Corps_project


# Claude-powered Oxygen Resource Navigator (CoviO2)
<img width="955" height="446" alt="image" src="https://github.com/user-attachments/assets/7eab281f-75a6-4373-b089-4f36c5aeac28" />

<img width="690" height="338" alt="image" src="https://github.com/user-attachments/assets/e5214d11-fda1-420f-acb7-4811808e7349" />


This repo contains a Claude-powered multilingual Oxygen Resource Navigator that converts static city-wise resource sheets into a helpdesk and matching engine for urgent oxygen requests.


## What it does
- Accepts incoming user messages in any supported city language and extracts city, language, resource need, urgency, and delivery preference.
- Matches the request to the best supplier listing from a normalized 15-city dataset using a lightweight retrieval + ranking layer.
- Generates a concise, localized reply with supplier contact details, eligibility notes, and a caution that the nonprofit only connects users to resources. Volunteers review and send the final response.
 
## Motivation
During COVID response work with CoviO2, volunteers manually identified city and language, searched static sheets, chose suppliers, and drafted responses—introducing delays and errors in urgent situations. This project automates that tedious workflow while keeping humans in the loop.


## Architecture
1. Data layer — Normalized city resource tables (city, resource, location, price, delivery, phone, verification date, language tags, confidence score).
2. Retrieval layer — Claude extracts structured fields from user text; a matcher queries indexed city listings and returns candidates.
3. Reasoning layer — Claude ranks candidates using rules: recent verification, delivery availability, resource match, fewer requirements for urgent requests, price/free options preference.
4. Response layer — Claude drafts a short, localized reply including contact info and a cautionary note; volunteer approves.
5. Volunteer dashboard & logging — Track requests, language, matched listing, resolution status (Airtable/Sheets/Notion).
## Getting started
1. Clone the repo.  
2. Populate /data with normalized CSVs for each city (fields: city, resource_type, location, price, delivery, phone, verification_date, requirements, language_tags, confidence_score).
3. Configure environment variables: CLAUDE_API_KEY, DATA_INDEX_PATH, DASHBOARD_DB_URL.  
4. Start the API server: python app.py (or the relevant entrypoint).  
5. Hook the messaging channel (WhatsApp/Telegram/website form) to POST incoming messages to /incoming. Claude will return JSON with extracted fields, matched listing, and a suggested reply.


## Prompts & Examples
- Extraction prompt: extract city, language, resource need, urgency, delivery preference; return JSON only.
- Ranking prompt: given candidate listings, rank top match and return a one-line reason.
- Reply prompt: draft a short reply in user language including contact details, requirements, and a caution that the org only connects to suppliers.
Example JSON output (simplified):
{
  "city":"Indore",
  "language":"Hindi",
  "resource":"Oxygen cylinder",
  "urgency":"high",
  "top_listing":{"name":"Supplier A","phone":"XXXXXXXX","price":"free","delivery":"yes"},
  "reply":"[Localized text with contact details and caution]"
}
 
## Volunteer workflow
- Volunteer receives the suggested reply in the dashboard, reviews contact details and instructions, edits if needed, and sends message.
- The system logs the request and outcome for analytics and verification updates.


## Safety and ethics
- The system includes a cautionary note that the nonprofit is *connecting* users to suppliers, not selling or endorsing them. Volunteers confirm listings before sending.
- Maintain privacy: log only necessary request metadata; do not store personal medical data unless required and with consent.
## Deployment notes
- Start with a single city (Indore) using the existing static sheet as a node, validate workflow and ranking, then roll out to additional cities incrementally.
- Use CLAUDE free-tier patterns: keep data local and use Claude for reasoning and language generation to reduce cost.
## Roadmap
- Add live verification status via volunteer updates.
- Expand language coverage and add voice-to-text input.
- Build analytics for response time, match accuracy, and volunteer load.


## Contributing
- Open issues for dataset format, prompt improvements, and UI enhancements.
- For dataset changes, follow the normalized CSV schema in /data/README.


## License
Choose an appropriate open-source license for your project (e.g., MIT).
