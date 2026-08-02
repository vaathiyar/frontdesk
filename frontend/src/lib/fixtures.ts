import type { CallRecord } from './types'

/**
 * Sample records, reproduced from what the backend actually serialises.
 *
 * Every field here is the shape `GET /api/calls/{id}` returns: a `CallRecord`
 * dumped by pydantic (`core/db/tables.py` -> `model_dump(mode="json")`). That
 * dump is why the two families of timestamp look different, and the difference
 * is real rather than sloppiness:
 *
 *   `started_at`, `ended_at`, and every `ts`   UTC, `Z` suffix, microseconds —
 *                                              they come from `datetime.now(UTC)`
 *   `booking.starts_at` / `booking.ends_at`    the business timezone's offset
 *                                              (`America/Vancouver`, so -07:00
 *                                              in summer), because
 *                                              `resolve_datetime` builds them
 *                                              with `tzinfo=timezone()`
 *
 * Event summaries are not paraphrases. Each is the exact string its emitter
 * formats — `worker/agent/tools.py` and `worker/lifecycle.py`:
 *
 *   availability_checked  `{pretty_day}: {open times, comma separated}`
 *   slot_declined         `{time} on {pretty_day} was not available`
 *   booking_created       `{service} on {spoken} for {key=value, key=value}`
 *   booking_rescheduled   `{service} on {spoken}`
 *   booking_cancelled     `{service} on {spoken}`
 *   message_taken         `{name}: {reason, truncated to 60 characters}`
 *   call_ended            `the agent ended the call`
 *   sms_sent              `to {caller_number} ({telnyx message id})`
 *   sms_skipped           the reason from `messaging/telnyx.py:skip_reason`
 *   sms_failed            `telnyx {status}: {code} {title}: {detail}`
 *
 * Ordering follows `lifecycle.py:finish_call`, which stamps `ended_at` first
 * and only then composes and sends the text — so an `sms_*` event legitimately
 * carries a timestamp *after* `ended_at`. `call_ended` lands before the final
 * agent turn, because `end_call` only marks the call over and the driver still
 * delivers the goodbye.
 *
 * Caller numbers all sit in the 555 exchange, so nothing here is dialable from
 * the `tel:` link on the record page. 555-0100..555-0199 is the block
 * `telnyx.py:RESERVED_FOR_FICTION` refuses to text, so a record with a caller
 * in that range carries `sms_skipped` and not `sms_sent` — that is what this
 * backend really does with those numbers, not a contrivance.
 *
 * Any id starting with `demo-` resolves from here instead of hitting the
 * network (dev only unless VITE_USE_FIXTURES=1). Real ids are UUIDs; these are
 * not, because `isFixtureId` routes on the prefix.
 */

function secondsAgo(seconds: number): string {
  // Padded to microseconds: pydantic dumps `datetime.now(UTC)` with six
  // fractional digits, and `toISOString()` only goes to three.
  return new Date(Date.now() - seconds * 1000).toISOString().replace('Z', '000Z')
}

/**
 * The hero path. `hvac.book` -> `save_booking` succeeds, so `Outcome.BOOKED`
 * with `availability_checked` then `booking_created` — the exact order
 * `tests/test_call_flow.py` asserts. `end_call` adds `call_ended` before the
 * goodbye is spoken, and the confirmation goes out after `ended_at`.
 */
const hvacBooked = (): CallRecord => ({
  id: 'demo-hvac-booked',
  profile_id: 'hvac',
  business_name: 'Helpdesk Heating and Cooling',
  caller_number: '+16045550234',
  called_number: '+16042969870',
  started_at: '2026-08-03T16:12:41.682809Z',
  ended_at: '2026-08-03T16:14:05.986886Z',
  outcome: 'booked',
  booking: {
    service: 'furnace repair',
    starts_at: '2026-08-04T10:00:00-07:00',
    ends_at: '2026-08-04T11:00:00-07:00',
    calendar_event_id: '7g3k9p2q1m8r4t6v0s5c2j8b1a',
    details: {
      name: 'Sam Lee',
      address: '12 Oak St, Burnaby',
      issue: 'no heat upstairs since last night',
    },
  },
  message: null,
  transcript: [
    {
      ts: '2026-08-03T16:12:41.682809Z',
      role: 'agent',
      text: 'Thanks for calling Helpdesk Heating and Cooling. How can I help?',
    },
    {
      ts: '2026-08-03T16:12:49.574824Z',
      role: 'caller',
      text: "My furnace quit overnight and there's no heat upstairs at all.",
    },
    {
      ts: '2026-08-03T16:12:56.564220Z',
      role: 'agent',
      text: "Sorry to hear that, especially overnight. Whereabouts are you, and what day suits you for a technician?",
    },
    {
      ts: '2026-08-03T16:13:07.339624Z',
      role: 'caller',
      text: 'Twelve Oak Street in Burnaby. Tomorrow if you can manage it.',
    },
    {
      ts: '2026-08-03T16:13:17.971090Z',
      role: 'agent',
      text: "Burnaby is in our area. Tomorrow I have ten in the morning, eleven, or two in the afternoon. Which would you like, and what name should I put it under?",
    },
    {
      ts: '2026-08-03T16:13:33.376513Z',
      role: 'caller',
      text: 'Ten works. Sam Lee.',
    },
    {
      ts: '2026-08-03T16:13:45.240900Z',
      role: 'agent',
      text: "Booked, Sam. A technician will be there Tuesday the fourth at ten in the morning for a furnace repair. I'll text you the details.",
    },
    {
      ts: '2026-08-03T16:13:57.442760Z',
      role: 'caller',
      text: "Perfect, that's everything. Thanks.",
    },
    {
      ts: '2026-08-03T16:14:01.611429Z',
      role: 'agent',
      text: "You're welcome. Stay warm, and we'll see you Tuesday.",
    },
  ],
  events: [
    {
      ts: '2026-08-03T16:13:14.157447Z',
      type: 'availability_checked',
      summary: 'Tuesday, August 4: 8:00 AM, 10:00 AM, 11:00 AM, 2:00 PM, 4:00 PM',
    },
    {
      ts: '2026-08-03T16:13:42.697552Z',
      type: 'booking_created',
      summary:
        'furnace repair on Tuesday, August 4 at 10:00 AM for name=Sam Lee, address=12 Oak St, Burnaby, issue=no heat upstairs since last night',
    },
    {
      ts: '2026-08-03T16:14:00.288412Z',
      type: 'call_ended',
      summary: 'the agent ended the call',
    },
    {
      ts: '2026-08-03T16:14:07.576555Z',
      type: 'sms_sent',
      summary: 'to +16045550234 (40017b1e-8f4a-4e9c-9c4d-2e5a1b3c7d90)',
    },
  ],
})

/**
 * The calendar refuses the time the caller asked for. `save_booking` catches
 * `SlotUnavailable` and emits `slot_declined` — note this fires when the
 * *calendar* says no, never when a caller turns a time down. The alternatives
 * that follow come from `_offer_alternatives`, which calls `available_slots`
 * directly rather than through the tool, so there is deliberately no second
 * `availability_checked` here.
 */
const hvacSlotDeclined = (): CallRecord => ({
  id: 'demo-hvac-slot-declined',
  profile_id: 'hvac',
  business_name: 'Helpdesk Heating and Cooling',
  caller_number: '+16045550341',
  called_number: '+16042969870',
  started_at: '2026-08-03T21:22:09.326213Z',
  ended_at: '2026-08-03T21:23:38.445759Z',
  outcome: 'booked',
  booking: {
    service: 'AC repair',
    starts_at: '2026-08-04T11:00:00-07:00',
    ends_at: '2026-08-04T12:00:00-07:00',
    calendar_event_id: '4m8p1c6h2v9t5k0b3n7q2j6r8d',
    details: {
      name: 'Dana Whitfield',
      address: '418 Sixth St, New Westminster',
      issue: 'AC blowing warm air',
    },
  },
  message: null,
  transcript: [
    {
      ts: '2026-08-03T21:22:09.326213Z',
      role: 'agent',
      text: 'Thanks for calling Helpdesk Heating and Cooling. How can I help?',
    },
    {
      ts: '2026-08-03T21:22:16.777278Z',
      role: 'caller',
      text: "My air conditioning is running but it's only blowing warm air.",
    },
    {
      ts: '2026-08-03T21:22:23.652202Z',
      role: 'agent',
      text: 'I can get someone out to look at that. What day and time were you hoping for, and can I take your name and address?',
    },
    {
      ts: '2026-08-03T21:22:38.590203Z',
      role: 'caller',
      text: "Tomorrow at eight if you have it. Dana Whitfield, four eighteen Sixth Street in New West.",
    },
    {
      ts: '2026-08-03T21:22:54.528252Z',
      role: 'agent',
      text: 'Eight is already taken tomorrow, sorry. I have eleven in the morning or two in the afternoon.',
    },
    {
      ts: '2026-08-03T21:23:07.103260Z',
      role: 'caller',
      text: 'Eleven works.',
    },
    {
      ts: '2026-08-03T21:23:19.159239Z',
      role: 'agent',
      text: "Booked, Dana. Tuesday the fourth at eleven for an AC repair, and I'll text you the details. Anything else?",
    },
    {
      ts: '2026-08-03T21:23:28.501235Z',
      role: 'caller',
      text: "No, that's it.",
    },
    {
      ts: '2026-08-03T21:23:33.436444Z',
      role: 'agent',
      text: 'Great. See you Tuesday.',
    },
  ],
  events: [
    {
      ts: '2026-08-03T21:22:41.369489Z',
      type: 'slot_declined',
      summary: '8:00 AM on Tuesday, August 4 was not available',
    },
    {
      ts: '2026-08-03T21:23:10.842306Z',
      type: 'booking_created',
      summary:
        'AC repair on Tuesday, August 4 at 11:00 AM for name=Dana Whitfield, address=418 Sixth St, New Westminster, issue=AC blowing warm air',
    },
    {
      ts: '2026-08-03T21:23:31.516090Z',
      type: 'call_ended',
      summary: 'the agent ended the call',
    },
    {
      ts: '2026-08-03T21:23:42.432547Z',
      type: 'sms_sent',
      summary: 'to +16045550341 (40017c93-1d6b-4a72-8e15-7b9f0c4d2a68)',
    },
  ],
})

/**
 * The second profile, on the same engine. `restaurant.book` collects a
 * different pair of details — `{name, party_size}`, both strings, as
 * `tests/test_call_flow.py` asserts — and the slot grid runs 5pm to 9pm
 * because the profile sets `opens=17, closes=22`.
 *
 * The caller sits in the reserved fictional block, so `send_sms` refuses
 * before any network call and the record carries `sms_skipped` with the exact
 * reason `skip_reason` produced.
 */
const kitchenBooked = (): CallRecord => ({
  id: 'demo-kitchen-booked',
  profile_id: 'restaurant',
  business_name: 'Helpdesk Kitchen',
  caller_number: '+16045550118',
  called_number: '+16042969871',
  started_at: '2026-07-31T23:38:52.468108Z',
  ended_at: '2026-07-31T23:40:03.958910Z',
  outcome: 'booked',
  booking: {
    service: 'table for 4',
    starts_at: '2026-08-01T19:00:00-07:00',
    ends_at: '2026-08-01T20:00:00-07:00',
    calendar_event_id: '9d2f7j4l1p6s3b8m0c5h2k9t4v',
    details: {
      name: 'Priya Raman',
      party_size: '4',
    },
  },
  message: null,
  transcript: [
    {
      ts: '2026-07-31T23:38:52.468108Z',
      role: 'agent',
      text: 'Thanks for calling Helpdesk Kitchen. How can I help you today?',
    },
    {
      ts: '2026-07-31T23:38:58.522595Z',
      role: 'caller',
      text: 'Do you have a table for four tomorrow evening?',
    },
    {
      ts: '2026-07-31T23:39:05.245349Z',
      role: 'agent',
      text: "Let me have a look at tomorrow. What name should I hold it under?",
    },
    {
      ts: '2026-07-31T23:39:16.799932Z',
      role: 'caller',
      text: 'Priya Raman. Four of us.',
    },
    {
      ts: '2026-07-31T23:39:23.990228Z',
      role: 'agent',
      text: 'Tomorrow I have five, seven or eight in the evening. Which suits you?',
    },
    {
      ts: '2026-07-31T23:39:36.599978Z',
      role: 'caller',
      text: 'Seven, please.',
    },
    {
      ts: '2026-07-31T23:39:47.245748Z',
      role: 'agent',
      text: "Done — a table for four on Saturday the first at seven, under Raman. I'll text you the details. Anything else?",
    },
    {
      ts: '2026-07-31T23:39:55.127236Z',
      role: 'caller',
      text: "That's everything, thank you.",
    },
    {
      ts: '2026-07-31T23:39:59.147649Z',
      role: 'agent',
      text: 'Lovely. See you tomorrow at seven.',
    },
  ],
  events: [
    {
      ts: '2026-07-31T23:39:19.119619Z',
      type: 'availability_checked',
      summary: 'Saturday, August 1: 5:00 PM, 7:00 PM, 8:00 PM, 9:00 PM',
    },
    {
      ts: '2026-07-31T23:39:39.311915Z',
      type: 'booking_created',
      summary:
        'table for 4 on Saturday, August 1 at 7:00 PM for name=Priya Raman, party_size=4',
    },
    {
      ts: '2026-07-31T23:39:58.260656Z',
      type: 'call_ended',
      summary: 'the agent ended the call',
    },
    {
      ts: '2026-07-31T23:40:05.960480Z',
      type: 'sms_skipped',
      summary: '+16045550118 is in the +1 (xxx) 555-01xx range reserved for fiction',
    },
  ],
})

/**
 * A party of twenty is past what the restaurant profile will book, so the
 * agent uses `take_message` instead of guessing. Note the event summary is
 * `f"{name}: {reason[:60]}"` — it really is cut mid-word at sixty characters,
 * while `message.reason` below keeps the whole thing.
 *
 * Telnyx rejects the send, so `_notify` records `sms_failed` and the call is
 * still saved: a failed text must not cost us the record.
 */
const kitchenMessage = (): CallRecord => ({
  id: 'demo-kitchen-message',
  profile_id: 'restaurant',
  business_name: 'Helpdesk Kitchen',
  caller_number: '+16045550407',
  called_number: '+16042969871',
  started_at: '2026-08-02T01:05:14.528682Z',
  ended_at: '2026-08-02T01:06:12.851070Z',
  outcome: 'message_taken',
  booking: null,
  message: {
    name: 'Marcus Bell',
    reason:
      'private dining for about 20 people on the 14th, wants a set menu and the back room if it is free',
  },
  transcript: [
    {
      ts: '2026-08-02T01:05:14.528682Z',
      role: 'agent',
      text: 'Thanks for calling Helpdesk Kitchen. How can I help you today?',
    },
    {
      ts: '2026-08-02T01:05:21.548187Z',
      role: 'caller',
      text: "I'm looking to do a private dinner for about twenty people on the fourteenth.",
    },
    {
      ts: '2026-08-02T01:05:30.601979Z',
      role: 'agent',
      text: "Twenty is more than I can book on the phone — that one goes to our manager. Can I take your name and pass it along?",
    },
    {
      ts: '2026-08-02T01:05:42.084079Z',
      role: 'caller',
      text: "Marcus Bell. I'd also like to know about a set menu, and whether the back room is free that night.",
    },
    {
      ts: '2026-08-02T01:05:55.644306Z',
      role: 'agent',
      text: "Got it, Marcus. I've passed that on and the manager will call you back. Anything else?",
    },
    {
      ts: '2026-08-02T01:06:04.871118Z',
      role: 'caller',
      text: "No, that's all.",
    },
    {
      ts: '2026-08-02T01:06:08.976708Z',
      role: 'agent',
      text: 'Thanks for calling. Someone will be in touch.',
    },
  ],
  events: [
    {
      ts: '2026-08-02T01:05:51.792363Z',
      type: 'message_taken',
      summary: 'Marcus Bell: private dining for about 20 people on the 14th, wants a set ',
    },
    {
      ts: '2026-08-02T01:06:07.505529Z',
      type: 'call_ended',
      summary: 'the agent ended the call',
    },
    {
      ts: '2026-08-02T01:06:14.077417Z',
      type: 'sms_failed',
      summary:
        'telnyx 422: 40305 Unsupported destination: The destination number cannot receive SMS from this messaging profile.',
    },
  ],
})

/**
 * Moving an appointment that was made on an *earlier* call.
 *
 * The empty `details` map is the accurate part, not an oversight: `reschedule`
 * writes `details=was.details if was else {}`, and `was` is
 * `record.booking` — which is null here, because this call has not booked
 * anything itself. The name and address the caller gave last time live on the
 * calendar event, not on this record.
 */
const hvacRescheduled = (): CallRecord => ({
  id: 'demo-hvac-rescheduled',
  profile_id: 'hvac',
  business_name: 'Helpdesk Heating and Cooling',
  caller_number: '+16045550266',
  called_number: '+16042969870',
  started_at: '2026-07-29T18:05:33.536837Z',
  ended_at: '2026-07-29T18:06:34.289620Z',
  outcome: 'rescheduled',
  booking: {
    service: 'AC tune-up',
    starts_at: '2026-07-30T15:00:00-07:00',
    ends_at: '2026-07-30T16:00:00-07:00',
    calendar_event_id: '2h6n9r3k7m1d4p8s0j5b2f6q9c',
    details: {},
  },
  message: null,
  transcript: [
    {
      ts: '2026-07-29T18:05:33.536837Z',
      role: 'agent',
      text: 'Thanks for calling Helpdesk Heating and Cooling. How can I help?',
    },
    {
      ts: '2026-07-29T18:05:39.755836Z',
      role: 'caller',
      text: "I've got a tune-up booked for Friday. Can I move it to Thursday?",
    },
    {
      ts: '2026-07-29T18:05:47.868411Z',
      role: 'agent',
      text: "Of course, let me see what Thursday looks like.",
    },
    {
      ts: '2026-07-29T18:05:55.616474Z',
      role: 'agent',
      text: 'Thursday I have nine, eleven, one or three. Which works best?',
    },
    {
      ts: '2026-07-29T18:06:06.101524Z',
      role: 'caller',
      text: 'Three in the afternoon.',
    },
    {
      ts: '2026-07-29T18:06:17.292776Z',
      role: 'agent',
      text: "Moved — your AC tune-up is Thursday the thirtieth at three now. I'll text you the new details. Anything else?",
    },
    {
      ts: '2026-07-29T18:06:26.599514Z',
      role: 'caller',
      text: "That's it, thanks.",
    },
    {
      ts: '2026-07-29T18:06:30.711058Z',
      role: 'agent',
      text: "You're welcome. See you Thursday.",
    },
  ],
  events: [
    {
      ts: '2026-07-29T18:05:50.755260Z',
      type: 'availability_checked',
      summary: 'Thursday, July 30: 9:00 AM, 11:00 AM, 1:00 PM, 3:00 PM',
    },
    {
      ts: '2026-07-29T18:06:09.858764Z',
      type: 'booking_rescheduled',
      summary: 'AC tune-up on Thursday, July 30 at 3:00 PM',
    },
    {
      ts: '2026-07-29T18:06:29.608146Z',
      type: 'call_ended',
      summary: 'the agent ended the call',
    },
    {
      ts: '2026-07-29T18:06:36.131822Z',
      type: 'sms_sent',
      summary: 'to +16045550266 (40018a2f-5c71-4d38-b046-9e2c8f1a5b37)',
    },
  ],
})

/**
 * A cancellation. `cancel` sets `record.booking = None` outright, so the
 * result panel has nothing to show and falls to its cancelled-specific copy —
 * that null is the backend's doing, not a gap in the fixture. The event
 * summary is whatever `CalendarService.cancel` returned, which is
 * `Booked.spoken()` for the appointment that was removed.
 */
const hvacCancelled = (): CallRecord => ({
  id: 'demo-hvac-cancelled',
  profile_id: 'hvac',
  business_name: 'Helpdesk Heating and Cooling',
  caller_number: '+16045550523',
  called_number: '+16042969870',
  started_at: '2026-07-30T15:47:02.503005Z',
  ended_at: '2026-07-30T15:47:34.257222Z',
  outcome: 'cancelled',
  booking: null,
  message: null,
  transcript: [
    {
      ts: '2026-07-30T15:47:02.503005Z',
      role: 'agent',
      text: 'Thanks for calling Helpdesk Heating and Cooling. How can I help?',
    },
    {
      ts: '2026-07-30T15:47:07.356651Z',
      role: 'caller',
      text: 'I need to cancel my tune-up on Friday.',
    },
    {
      ts: '2026-07-30T15:47:17.872112Z',
      role: 'agent',
      text: "That's cancelled — the AC tune-up on Friday the thirty-first at two. Anything else?",
    },
    {
      ts: '2026-07-30T15:47:26.922706Z',
      role: 'caller',
      text: "No, that's all.",
    },
    {
      ts: '2026-07-30T15:47:30.246199Z',
      role: 'agent',
      text: 'No problem at all. Take care.',
    },
  ],
  events: [
    {
      ts: '2026-07-30T15:47:14.910320Z',
      type: 'booking_cancelled',
      summary: 'AC tune-up on Friday, July 31 at 2:00 PM',
    },
    {
      ts: '2026-07-30T15:47:29.270006Z',
      type: 'call_ended',
      summary: 'the agent ended the call',
    },
    {
      ts: '2026-07-30T15:47:36.421173Z',
      type: 'sms_sent',
      summary: 'to +16045550523 (40018d54-2b90-4f16-a7c3-1d6e5b802f49)',
    },
  ],
})

/**
 * Questions answered and nothing scheduled. No tool set an outcome, so
 * `lifecycle.py:_what_happened` infers `ANSWERED` from the fact that the
 * caller spoke at all.
 *
 * The absence of any `sms_*` event is the point: `confirmation()` returns ""
 * when there is no booking, no cancellation and no message, `compose_sms`
 * passes that straight through, and `finish_call` then skips `_notify`
 * entirely. Someone who only asked the opening hours does not get a text.
 */
const hvacAnswered = (): CallRecord => ({
  id: 'demo-hvac-answered',
  profile_id: 'hvac',
  business_name: 'Helpdesk Heating and Cooling',
  caller_number: '+16045550171',
  called_number: '+16042969870',
  started_at: '2026-07-31T20:20:46.321405Z',
  ended_at: '2026-07-31T20:21:46.315436Z',
  outcome: 'answered',
  booking: null,
  message: null,
  transcript: [
    {
      ts: '2026-07-31T20:20:46.321405Z',
      role: 'agent',
      text: 'Thanks for calling Helpdesk Heating and Cooling. How can I help?',
    },
    {
      ts: '2026-07-31T20:20:52.309824Z',
      role: 'caller',
      text: 'Do you cover Coquitlam, and what are your hours?',
    },
    {
      ts: '2026-07-31T20:21:03.083189Z',
      role: 'agent',
      text: "We do — Burnaby, New Westminster and Coquitlam. We're open Monday to Saturday, eight in the morning to six in the evening.",
    },
    {
      ts: '2026-07-31T20:21:17.662323Z',
      role: 'caller',
      text: 'And is an estimate on a new furnace free?',
    },
    {
      ts: '2026-07-31T20:21:26.996569Z',
      role: 'agent',
      text: 'Estimates on new installations are free, yes.',
    },
    {
      ts: '2026-07-31T20:21:36.036293Z',
      role: 'caller',
      text: "Good to know. I'll call back once I've decided.",
    },
    {
      ts: '2026-07-31T20:21:42.588395Z',
      role: 'agent',
      text: 'Sounds good. Thanks for calling.',
    },
  ],
  events: [
    {
      ts: '2026-07-31T20:21:41.497895Z',
      type: 'call_ended',
      summary: 'the agent ended the call',
    },
  ],
})

/**
 * The caller hung up on the greeting. `_what_happened` returns `ABANDONED`
 * because no turn has `role == "caller"`.
 *
 * One transcript entry and zero events is exactly right: `session.py` records
 * the greeting on the record before speaking it, nothing else ever ran, and
 * with no booking or message there is nothing to text about either.
 */
const hvacAbandoned = (): CallRecord => ({
  id: 'demo-hvac-abandoned',
  profile_id: 'hvac',
  business_name: 'Helpdesk Heating and Cooling',
  caller_number: '+16045550188',
  called_number: '+16042969870',
  started_at: '2026-08-01T14:58:23.211640Z',
  ended_at: '2026-08-01T14:58:37.620791Z',
  outcome: 'abandoned',
  booking: null,
  message: null,
  transcript: [
    {
      ts: '2026-08-01T14:58:23.211640Z',
      role: 'agent',
      text: 'Thanks for calling Helpdesk Heating and Cooling. How can I help?',
    },
  ],
  events: [],
})

/**
 * A call still on the line: no `ended_at`, no outcome, nothing settled yet.
 *
 * Worth knowing where this shape comes from. In production it is never served,
 * because `SqlCallStore.save` is only ever called from `finish_call` on
 * hang-up — the row does not exist until the call is over. It is reachable
 * through `scripts/seed_call.py --kind live`, which writes exactly this, and
 * it is the shape the record page is most likely to render wrong.
 */
const hvacLive = (): CallRecord => ({
  id: 'demo-live',
  profile_id: 'hvac',
  business_name: 'Helpdesk Heating and Cooling',
  caller_number: '+16045550312',
  called_number: '+16042969870',
  started_at: secondsAgo(47),
  ended_at: null,
  outcome: null,
  booking: null,
  message: null,
  transcript: [
    {
      ts: secondsAgo(47),
      role: 'agent',
      text: 'Thanks for calling Helpdesk Heating and Cooling. How can I help?',
    },
    {
      ts: secondsAgo(38),
      role: 'caller',
      text: 'Hi, I think my AC is leaking water onto the floor.',
    },
    {
      ts: secondsAgo(29),
      role: 'agent',
      text: "That's worth looking at soon. What day works for you, and can I take your name and address?",
    },
    {
      ts: secondsAgo(14),
      role: 'caller',
      text: 'Tomorrow morning if possible.',
    },
  ],
  events: [
    {
      ts: secondsAgo(21),
      type: 'availability_checked',
      summary: 'Monday, August 3: 8:00 AM, 9:00 AM, 1:00 PM',
    },
  ],
})

/**
 * A backend newer than this frontend.
 *
 * `types.ts` types `outcome` and `event.type` as free strings precisely so the
 * UI keeps working when the backend grows a value it has never seen, and this
 * record is what exercises that: an unrecognised outcome and an unrecognised
 * event type, both of which must humanize rather than crash or leak
 * snake_case. The non-NANP caller number exercises the other `formatPhone`
 * branch, and it is genuinely reachable — `to_e164` passes through any number
 * that already carries its `+`.
 *
 * The two unknowns are not equally far off. `CallEvent.type` is a plain `str`,
 * so `warm_transfer_attempted` would validate against today's model as-is and
 * only needs a new `emit` call to become real. `Outcome` is a closed StrEnum,
 * so `callback_scheduled` is the one field on this page that today's backend
 * would reject outright; it needs a new enum member first. Every other record
 * in this file round-trips through `CallRecord` unchanged, and this one does
 * too once the outcome is swapped for a known value.
 *
 * What it does *not* do is invent an impossible wire shape. `details` is
 * `dict[str, str]` on the backend and pydantic rejects anything else, so every
 * value here is a string; `role` only ever comes out as "caller" or "agent"
 * (`session.py` maps user/assistant and drops the rest). A null
 * `calendar_event_id` is real — the field is `str | None` — and gives the
 * booking panel's "not written to the business calendar" branch something to
 * render.
 */
const unknownShapes = (): CallRecord => ({
  id: 'demo-unknown-shapes',
  profile_id: 'hvac',
  business_name: 'Helpdesk Heating and Cooling',
  caller_number: '+447700900412',
  called_number: '+16042969870',
  started_at: '2026-08-01T22:02:11.291488Z',
  ended_at: '2026-08-01T22:03:16.776900Z',
  outcome: 'callback_scheduled',
  booking: {
    service: 'AC tune-up',
    starts_at: '2026-08-04T09:00:00-07:00',
    ends_at: '2026-08-04T10:00:00-07:00',
    calendar_event_id: null,
    details: {
      name: 'Marguerite Okonkwo-Bell',
      address: '1140 Carnarvon St, New Westminster',
      issue: 'rooftop unit needs its annual service',
      unit_access_code: '4417',
      site_contact: 'building manager, +16045550119',
      notes: 'Roof access needs 24h notice from the strata.',
    },
  },
  message: null,
  transcript: [
    {
      ts: '2026-08-01T22:02:11.291488Z',
      role: 'agent',
      text: 'Thanks for calling Helpdesk Heating and Cooling. How can I help?',
    },
    {
      ts: '2026-08-01T22:02:20.897865Z',
      role: 'caller',
      text: "I'm calling from the UK about a rooftop unit on a building in New Westminster.",
    },
    {
      ts: '2026-08-01T22:02:37.097750Z',
      role: 'agent',
      text: 'New Westminster is in our area. I have nine in the morning on Tuesday. Who should the technician ask for on site?',
    },
    {
      ts: '2026-08-01T22:02:49.684384Z',
      role: 'caller',
      text: 'The building manager. But roof access needs a day of notice from the strata.',
    },
    {
      ts: '2026-08-01T22:03:03.818261Z',
      role: 'agent',
      text: "Noted. I've put Tuesday at nine down and flagged the roof access, and someone will confirm with the strata before then.",
    },
    {
      ts: '2026-08-01T22:03:12.454454Z',
      role: 'agent',
      text: 'Thanks for calling. Someone will be in touch shortly.',
    },
  ],
  events: [
    {
      ts: '2026-08-01T22:02:32.314296Z',
      type: 'availability_checked',
      summary: 'Tuesday, August 4: 9:00 AM, 1:00 PM, 3:00 PM',
    },
    {
      ts: '2026-08-01T22:02:58.503932Z',
      type: 'warm_transfer_attempted',
      summary: 'no dispatcher available, stayed on the line',
    },
    {
      ts: '2026-08-01T22:03:11.769511Z',
      type: 'call_ended',
      summary: 'the agent ended the call',
    },
    {
      ts: '2026-08-01T22:03:18.400589Z',
      type: 'sms_sent',
      summary: 'to +447700900412 (40019f07-6a83-4c25-9b71-3f8d2e6c0a15)',
    },
  ],
})

export const FIXTURES: Record<string, () => CallRecord> = {
  'demo-hvac-booked': hvacBooked,
  'demo-hvac-slot-declined': hvacSlotDeclined,
  'demo-kitchen-booked': kitchenBooked,
  'demo-kitchen-message': kitchenMessage,
  'demo-hvac-rescheduled': hvacRescheduled,
  'demo-hvac-cancelled': hvacCancelled,
  'demo-hvac-answered': hvacAnswered,
  'demo-hvac-abandoned': hvacAbandoned,
  'demo-live': hvacLive,
  'demo-unknown-shapes': unknownShapes,
}

/** Ids that force a non-success state so all three can be reviewed. */
export const STATE_FIXTURES = {
  loading: 'demo-loading',
  missing: 'demo-missing',
  failed: 'demo-error',
} as const

export interface FixtureLink {
  id: string
  label: string
  note: string
}

export const FIXTURE_LINKS: FixtureLink[] = [
  { id: 'demo-hvac-booked', label: 'Booked', note: 'HVAC · furnace repair · SMS sent' },
  { id: 'demo-hvac-slot-declined', label: 'Slot declined', note: 'HVAC · calendar refused 8am' },
  { id: 'demo-kitchen-booked', label: 'Booked', note: 'Restaurant · SMS skipped' },
  { id: 'demo-kitchen-message', label: 'Message taken', note: 'Restaurant · SMS failed' },
  { id: 'demo-hvac-rescheduled', label: 'Rescheduled', note: 'HVAC · no details carried over' },
  { id: 'demo-hvac-cancelled', label: 'Cancelled', note: 'HVAC · booking cleared' },
  { id: 'demo-hvac-answered', label: 'Answered', note: 'Questions only · no text sent' },
  { id: 'demo-hvac-abandoned', label: 'Abandoned', note: 'Hung up on the greeting' },
  { id: 'demo-live', label: 'In progress', note: 'No end time, still on the line' },
  { id: 'demo-unknown-shapes', label: 'Unknown shapes', note: 'Unseen outcome and event type' },
  { id: STATE_FIXTURES.loading, label: 'Loading state', note: 'Never resolves' },
  { id: STATE_FIXTURES.missing, label: 'Not found state', note: '404 from the API' },
  { id: STATE_FIXTURES.failed, label: 'Error state', note: 'Network failure' },
]

export function isFixtureId(id: string): boolean {
  return id.startsWith('demo-')
}
