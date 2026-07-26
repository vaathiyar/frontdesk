# AI Receptionist — Backend

One engine, swappable **call profiles**. A caller reaches the agent, which books /
reschedules / cancels an appointment on the same call, answers questions about the
business, or takes a message — and produces one `CallRecord` (transcript, decision
timeline, outcome, booking) that the email summary and web detail view both read.

Design & rationale: **[`../docs/lld.md`](../docs/lld.md)**. Requirements: [`../docs/poc_requirements_p0.md`](../docs/poc_requirements_p0.md).

> All commands below run from this `backend/` directory.

## Status

This milestone is the **brain + the dev harness**: the profile engine, the six tools,
the tool-use loop, and a text REPL to drive it — all runnable and tested with no
network. The voice stack (LiveKit + GCP STT/TTS), CockroachDB persistence, and the web
app are designed in `../docs/lld.md` and deferred to later milestones.

## Quickstart

```bash
uv sync --extra dev          # create .venv, install deps
uv run pytest                # 34 tests, no network, no API key needed

# To chat with the agent you need an LLM credential:
export ANTHROPIC_API_KEY=sk-ant-...     # or run `ant auth login`
uv run python scripts/chat.py hvac      # also: restaurant | auto
```

Type as the caller. On exit the harness prints the resulting `CallRecord` — outcome,
captured fields, the code-emitted decision timeline, and the signed share link:

```
caller> my furnace quit, can someone come Tuesday morning?
agent>  I can help with that. ...
...
────────────────────────────────────────────────────────────────
  CallRecord 3f2a…   profile: hvac   caller: +1-555-0100
  outcome: booked
  booking: furnace repair @ Tuesday 10:00 AM  (evt_1a2b3c4d)
  fields:  name='Sam Lee', address='12 Oak St', issue='no heat', email='sam@example.com'
  decision timeline:
    • availability_checked: Tuesday: 10:00 AM, 1:00 PM, 3:00 PM
    • booking_created: furnace repair — Tuesday 10:00 AM
  share link: /c/3f2a…?t=…
```

The fake calendar seeds **tomorrow 8:00 AM as busy**, so ask for it to watch the agent
decline and offer another time — and note it never claims a booking the tool didn't make.

## Add a profile

The extension model in one file — no engine changes:

```python
# src/receptionist/profiles/dental.py
class DentalReceptionist(Receptionist):
    profile_id = "dental"
    business_name = "Riverside Dental"
    greeting = "Thanks for calling Riverside Dental!"

    def domain_prompt(self) -> str: ...  # role, services, tone
    def booking_fields(self) -> list[Field]:
        return [NAME, ..., EMAIL]

    def knowledge(self) -> str: ...  # facts for answer_question
```

Then one line in `src/receptionist/profiles/factory.py`: `"dental": DentalReceptionist`.

## Layout

```
src/receptionist/
  core/        CallRecord + repository interface + links + settings   (shared contract)
  profiles/    Receptionist base + hvac/restaurant/auto + factory     (extension surface)
  services/    CalendarService interface + seeded FakeCalendarService
  agent/       ConversationRunner (the tool-use loop)
  persistence/ InMemoryCallRepository (CockroachDB later)
scripts/chat.py   the dev REPL
tests/            offline coverage (fake calendar + fake LLM)
```

## Quality

```bash
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run pytest
```
