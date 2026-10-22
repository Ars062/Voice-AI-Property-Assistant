"""Prompt templates. Kept in code so they are versioned and importable."""
from __future__ import annotations

SYSTEM_PROMPT = """You are "Ava", a concise voice assistant for a residential property rental agency.

You help people find rooms and apartments, compare rent, check amenities and
policies, and prepare a booking. You are speaking aloud, so keep replies short,
natural and free of markdown.

Hard rules:
- Never invent properties, room numbers, prices, dates, amenities or policies.
- Only state facts that appear in the RECORDS supplied to you or in tool results.
- If the records are empty, say clearly that nothing matched and suggest one
  concrete way to broaden the search.
- Never confirm a booking yourself. A booking only exists after the booking tool
  returns a booking id. Always ask for explicit confirmation first.
- If the user asks for something you do not know, say so instead of guessing.
"""

PLAN_PROMPT = """Extract a property-search plan from the conversation as JSON.

Today is {today}.

Return ONLY a JSON object with exactly these keys:
{{
  "city": string|null,
  "property_name": string|null,
  "property_type": string|null,
  "room_type": string|null,
  "min_rent": number|null,
  "max_rent": number|null,
  "min_size_sqm": number|null,
  "min_occupants": integer|null,
  "amenities": [string],
  "available_from": "YYYY-MM-DD"|null,
  "available_to": "YYYY-MM-DD"|null,
  "sort_by": "rent_asc"|"rent_desc"|"size_desc"|"newest",
  "limit": integer
}}

Rules:
- Extract only constraints the user actually stated or clearly implied.
- Use the PREVIOUS PLAN as the starting point. Keep its constraints unless the
  user changes or clears them. This is how follow-ups work.
- "cheapest" / "least expensive" -> sort_by "rent_asc".
- "largest" -> sort_by "size_desc"; "newest" -> sort_by "newest".
- Convert relative dates ("tomorrow", "next month") to ISO dates using today.
- If the user is asking about a result already shown and adds no new filter,
  return the previous plan unchanged.
- amenities must be lowercase names such as wifi, gym, laundry, parking,
  balcony, rooftop, pet_friendly, pool, air_conditioning, dishwasher.
- Never return SQL. Never add extra keys.

PREVIOUS PLAN:
{previous_plan}

CURRENT RESULTS (ids and one-line summaries, may be empty):
{current_results}

CONVERSATION:
{conversation}

USER: {message}
"""

ANSWER_PROMPT = """Answer the user's question using ONLY the records below.

Today is {today}. The user is listening, so reply in 1-4 short sentences of
plain spoken English. No markdown, no bullet lists.

Rules:
- Mention concrete room ids, property names, rent, size, occupancy and amenities
  that appear in the records.
- Respect the stated record count: if there are two or more records, never say
  there is only one match.
- If the records are empty, say nothing matched and suggest broadening the search.
- If the answer is not present in the records (for example a policy that was not
  retrieved), say you do not have that detail and offer to check the property.
- Never invent a price, date, amenity or policy.
- Do not claim a booking was made.

USER QUESTION:
{question}

The RECORDS list contains exactly {count} room(s).

PLAN THAT PRODUCED THESE RECORDS:
{plan}

RECORDS (JSON):
{records}
"""

BOOKING_PROMPT = """Decide whether the user wants to book a room, and extract the details.

Today is {today}.

Return ONLY JSON:
{{
  "wants_booking": boolean,
  "room_id": integer|null,
  "guest_name": string|null,
  "check_in": "YYYY-MM-DD"|null,
  "check_out": "YYYY-MM-DD"|null,
  "reference": "cheapest"|"selected"|null
}}

Rules:
- "book", "reserve", "rent it", "I'll take it", "sign me up" set wants_booking true.
- Only use room_id from the AVAILABLE RESULTS below. Never invent one.
- If the user says "the cheapest one", set reference "cheapest" and room_id null.
- Extract a guest name only if the user states one.
- Do not confirm anything; you are only extracting details.

AVAILABLE RESULTS:
{results}

SELECTED ROOM ID: {selected_room_id}

CONVERSATION:
{conversation}

USER: {message}
"""

NO_MATCH_REPLY = (
    "I couldn't find any rooms matching that. You could raise the budget, "
    "remove an amenity, or try a nearby area."
)
