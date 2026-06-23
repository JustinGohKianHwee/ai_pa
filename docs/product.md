# Product Vision

## What this is

A private, modular AI personal assistant and personal operating system. Not a task app, a
finance tracker, a calendar, or a notes tool — it is a unified layer that sits across all
of those domains and connects them through a single capture-and-review interface.

The end state: a system that knows your life data as well as you do, helps you stay on top
of what matters, and gives you structured visibility into your own patterns — without
ever taking action behind your back.

---

## Core user experience

You speak or type naturally — through Telegram, a voice note, or a web form — and the
assistant handles the rest:

1. It receives your input exactly as you gave it
2. It transcribes voice to text if needed
3. It classifies what you meant (task? expense? food log? calendar plan? note?)
4. It extracts structured data (amount, date, person, category, urgency, etc.)
5. It places a classified pending item in your review inbox
6. You review the item, optionally edit it, and confirm or reject it
7. Confirmation creates a permanent domain record only when that domain module exists

You are always in control. The AI does the classification and extraction. You make the
final call.

---

## Example interactions

| What you say | What it becomes |
|-------------|----------------|
| "Remind me to pay my credit card next Friday" | Task with due date |
| "Spent $12.50 on lunch at Tanjong Pagar" | Finance expense, pending review |
| "Ate chicken rice and kopi for lunch" | Food log, pending review |
| "Buy $350 CSPX this month" | Investment note, pending review |
| "Dinner with Zoey next Friday 7pm at Jewel" | Calendar intent, pending review |
| "I felt distracted today because of context switching" | Journal / reflection note |
| "Remember I prefer term insurance over whole life" | Personal preference / memory candidate |

---

## Target life domains

Each domain is a separate module. They share the same capture and review pipeline but
store confirmed records in their own tables and have their own views.

- **Tasks and reminders** — things to do, with urgency and due dates
- **Personal finance** — expenses, income, net worth tracking
- **Food and nutrition** — meals, calories, protein, macros
- **Calendar and scheduling** — intended events and appointments
- **Investment notes** — planned or recorded investment actions
- **Journal and reflection** — free-form notes, daily feelings, observations
- **Daily planning** — morning intention-setting, evening review
- **Goals and habits** — recurring commitments and tracked habits
- **Notes** — everything that does not fit a structured category
- **Future: email, documents, life admin, deeper assistant workflows**

---

## The review-before-action principle

This is the most important product principle. It is not a temporary limitation — it is
intentional design.

**The assistant must never take a final action without explicit user confirmation.**

Sensitive actions that always require confirmation:
- Creating a calendar event
- Sending a message or email
- Confirming a financial record
- Writing an investment transaction
- Deleting or overwriting any record
- Confirming a health or food entry
- Any action that is hard or impossible to reverse

Why this matters:
- AI classification is not perfect. It will sometimes misclassify your input.
- Your personal data (money, health, schedule) is too important to get wrong silently.
- A review step means the AI does the work of structuring your data, but you stay accountable for its accuracy.
- The inbox is also a daily touchpoint — a moment to consciously process what you captured.

---

## The capture → review → confirm pipeline

Every piece of data in this system follows the same path:

```
[1] CAPTURE
    Raw input arrives (text, voice, Telegram message)
    Stored as an immutable capture_event

[2] CLASSIFY / EXTRACT
    AI determines intent and extracts structured fields
    Creates an inbox_item with review_status = pending
    The original raw input fields are never modified

[3] PENDING INBOX  ← first end-to-end milestone (Phases 4–6)
    Classified item waits for user review
    User can see AI's interpretation and extracted data
    User can edit any field before confirming

[4] REVIEW
    User reviews the pending inbox item
    User edits if needed
    User confirms or rejects

[5] ATOMIC CONFIRMATION
    Explicit user confirmation validates item_type and structured_json
    If the domain module exists, exactly one linked domain record is created
    inbox_item review_status becomes confirmed and reviewed_at is recorded
    These writes occur in one transaction with no visible intermediate state
    Before a domain module exists, confirmation only updates the inbox_item review state

[6] AUDIT
    capture_events preserve raw input, agent_runs audit AI calls, and inbox_items
    preserve review_status and review timestamps
```

Nothing skips the review gate. Not tasks, not finance items, not calendar plans. Every
capture remains reviewable until you explicitly confirm or reject it.

---

## What the assistant does

- Receives input from any connected capture surface (Telegram, voice, web form)
- Transcribes voice notes to text
- Classifies the intent of natural language input
- Extracts structured data fields (dates, amounts, names, categories)
- Presents classified items for review in the dashboard inbox
- Stores confirmed records in the right domain module
- Surfaces past data through queries, summaries, reviews, and a chronological life timeline
- Logs all AI actions for transparency

---

## What the assistant does not do

- Automatically create calendar events
- Automatically send messages or emails on your behalf
- Automatically confirm financial records without your review
- Automatically delete or overwrite records
- Make investment decisions or execute trades
- Take any irreversible action without explicit confirmation
- Learn from your data in ways you cannot inspect or undo

---

## Why modular, not monolithic

Each life domain (tasks, finance, food, calendar, etc.) has different:
- Data shapes
- Review workflows
- Display requirements
- Integration needs

Building them as separate modules means:
- Each module can be built, tested, and broken independently
- You can ship the system with only tasks working and add finance later
- A bug in the food log module cannot break the task module
- Each module can evolve at its own pace
- New domains (email, documents) can be added without touching existing code

The capture pipeline is shared. The domain modules are separate.
