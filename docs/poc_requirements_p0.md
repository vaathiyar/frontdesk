# AI Receptionist PoC — Build Checklist

**Model:** Inbound only. Caller dials → agent answers live → books on the *same* call → owner notified. No outbound / no callback.
**Goal:** One engine, two swappable profiles. **HVAC = the one you build and sell first**; Restaurant exists so the demo flexes to a different kind of room. *(A third vertical — Auto — is parked for now; see "Out of scope for v1" below.)*

---

## Stack (decided defaults)
- [ ] **Voice:** self-hosted LiveKit + a SIP **inbound** trunk + dispatch rule → your agent
- [ ] **Trunk / number:** VoIP.ms (cheapest, Canadian) *or* Telnyx — a **local** Canadian DID, **pay-per-minute** mode (NOT per-channel). ≈1.5–2¢/call.
- [ ] **Booking:** one Google Calendar per profile (free/busy read + event create)
- [ ] **Notify:** Google Calendar invite (free) + optional summary email via Gmail API or your own SMTP
- [ ] **SMS:** skip for v1 (10DLC registration overhead — add later for a paying customer)
- [ ] **One phone number per profile** (dial the HVAC number → HVAC agent)

## The engine (build once)
`answer → greet + business name → detect intent → collect fields → check availability → act → confirm back → notify owner`
Intents: `book | reschedule | cancel | question | urgent | human`
**Universal fallback at every step:** if confused OR caller asks for a person → transfer / take a message. **No call ever ends without name + callback # + reason.**

## Profile config (the only thing that changes between verticals)
```
Profile {
  business:      { name, hours, service_area, fees }
  bookable:      [ services... ]            // or "reservation"
  faqs:          [ {q, a} × ~10 ]
  fields:        [ per-booking fields to collect ]
  urgent:        { triggers[], action }
  notify:        { email[], oncall_number }
  phone_number
}
```

**HVAC (hero) — "Westside Heating & Cooling"** — serves Burnaby / New West / Coquitlam
- bookable: furnace repair, furnace replace *(quote)*, AC repair, AC install *(quote)*, maintenance/tune-up, thermostat, no-heat emergency, no-cool emergency
- fields: name · phone *(read back digit-by-digit + confirm)* · **service address (confirm in-area)** · issue description · system type · urgent? · preferred day+window
- fees: $119 service call (waived if repair proceeds); free install quotes
- urgent tiers:
  - **Safety** — gas smell / CO alarm / burning smell → tell caller to leave + call gas utility or 911, **do NOT book**, escalate immediately. No technical instructions.
  - **Comfort** — no heat / no cooling / leak → flag URGENT, offer soonest or after-hours slot, alert owner now.
  - **Routine** — everything else → normal flow.

**Restaurant — "Bianca Trattoria"** *(deltas only)*
- bookable: **table reservation only** — takeout ordering is out of scope
- fields: party size · date · time · name · phone · special requests
- escalation: party > ~8 or private-event inquiry → hand to manager

## Build tasks
- [ ] SIP inbound trunk + dispatch rule routing calls into the agent room
- [ ] Profile loader (config object drives all agent behavior)
- [ ] Intent detection across the 6 intents
- [ ] Field collection with **digit-by-digit phone readback + explicit confirm**
- [ ] Calendar **free/busy read** (seed a few busy blocks so the demo shows it *declining* a taken slot)
- [ ] Calendar **event create** — description carries every captured field
- [ ] Reschedule / cancel (find existing event → move / remove)
- [ ] Human handoff — warm transfer to owner's cell
- [ ] Message-capture fallback (name + # + reason)
- [ ] Urgent detection + escalation path (per profile)
- [ ] Owner notification: calendar invite + summary email (caller, #, intent, outcome, URGENT flag, transcript link)
- [ ] Log every call: full transcript + recording + structured fields

## Acceptance criteria — must ALL pass (these are the deal-killers)
- [ ] Never offers a time that's busy on the connected calendar
- [ ] Reads back the phone number and gets an explicit "yes" before ending
- [ ] Confirms the full booking (service + date + time + location) back to the caller
- [ ] **Never claims it booked something it didn't**
- [ ] Caller asks for a person → transfer / message within one turn, no arguing
- [ ] After ~2 failed clarification attempts → falls back to message capture
- [ ] No call ends without a name + callback number (unless the caller refuses)
- [ ] Greets and states the business name within ~1s of pickup
- [ ] Handles barge-in (caller talks over it) without breaking
- [ ] Response latency ~≤1s; never freezes on silence (re-prompt, then fall back)
- [ ] HVAC: gas / CO / burning smell → evacuation advice + escalation, **never** booked as routine

## Test calls (prove the safety net)
- [ ] Happy path: "furnace quit, house is cold" → books tomorrow 8am, owner pinged URGENT
- [ ] Caller mumbles the number → agent re-confirms the digits
- [ ] Tries to book an already-taken slot → agent declines, offers next opening
- [ ] Off-menu ("do you do commercial boilers?") → doesn't bluff → message / handoff
- [ ] "I smell gas" → evacuate + escalate, no booking created

## Out of scope for v1 (resist building these)
Payments / deposits · outbound calling · analytics dashboard · takeout ordering · syncing to anything beyond the one calendar. Prove the loop first.

**Parked profile:** an **Auto / automotive** vertical ("Lougheed Auto Repair") — deferred beyond this build's HVAC + Restaurant scope. The engine is profile-swappable, so it drops back in as another profile (vehicle year/make/model + drop-off/wait fields) when a customer wants it.