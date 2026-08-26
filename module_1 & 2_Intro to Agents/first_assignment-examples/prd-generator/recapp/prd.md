# Recapp

## 1. Problem Statement

People running recurring meetings, whether it's a weekly team standup, a client check-in, or a project sync, typically take notes in whatever tool is closest at hand: a notebook, a random doc, a chat message, or their memory. Over time, these notes pile up in scattered, disconnected places. When someone asks "what did we decide last time?" or "who was supposed to follow up on this?", there is no single place to look. This leads to repeated discussions, dropped tasks, and lost accountability.

This matters now because remote and hybrid work has multiplied the number of recurring meetings people attend, while note-taking habits have not kept pace. Individuals and small teams do not have the budget, patience, or need for a heavyweight, login-required project management tool. They need something simple, fast, and private that just works on their own machine, without setup friction or data leaving their device.

## 2. Goals

- Increase the percentage of meetings with a findable, structured record from an estimated 20% (scattered notes) to 80% within 3 months of adoption.
- Reduce the average time to find a past decision or action item from over 5 minutes (searching multiple sources) to under 30 seconds within 3 months.
- Increase the percentage of action items with a clear owner and status from under 30% to 90% within 3 months.
- Achieve a 60% week-over-week return rate for users who log a second meeting within 14 days of their first.
- Reduce reported instances of "we already discussed this" repeat conversations by 50%, based on user self-reporting surveys, within 6 months.

## 3. Non-Goals

- Recapp will not include real-time transcription or audio recording of meetings.
- Recapp will not integrate with calendars, video conferencing tools, or third-party APIs in the initial version.
- Recapp will not support multi-user real-time collaboration or shared cloud sync.
- Recapp will not require or support user accounts, login, or authentication of any kind.
- Recapp will not send notifications, reminders, or emails to users or their teammates.
- Recapp will not analyze meeting sentiment, generate AI summaries, or provide coaching feedback on meeting quality.
- Recapp will not store any data on a remote server or backend; everything stays local to the user's device.

## 4. Users & Use Cases

**Primary users:** Individuals who run or attend recurring meetings, and small teams (2 to 10 people) who need a lightweight shared reference without adopting a full project management suite.

**Scenario 1: The weekly team lead**
Maria runs a weekly product sync with four teammates. Each week, she used to jot notes in a random Google Doc, then forget which doc had last week's decisions. With Recapp, she opens the app, selects "Product Sync" from her list of recurring meetings, and quickly logs the decisions made and who owns each follow-up task. Before next week's meeting, she opens Recapp, glances at last week's action items, and immediately knows what to check in on.

**Solo consultant tracking client calls**
David is an independent consultant who has weekly calls with three different clients. He used to lose track of which client asked for what. Now he creates a separate recurring meeting entry in Recapp for each client. During and after each call, he types quick notes and marks decisions and owners. When a client emails asking "did we agree on X?", David searches Recapp locally and finds the answer in seconds, without digging through old emails.

**Small team without a project manager**
A five-person startup team holds a biweekly planning meeting but has no dedicated project manager to track outcomes. One team member opens Recapp on their laptop during the meeting, types up decisions and assigns owners in real time, and exports a simple summary at the end. The team pastes that summary into their existing chat tool so everyone has a shared reference, without needing a new shared account or login.

## 5. User Stories

### Must-have

- As a meeting organizer, I want to create a named recurring meeting so that I can keep notes for that meeting series in one place.
- As a meeting organizer, I want to add a new note entry (dated) under a specific meeting so that I can log what happened in that session.
- As a user, I want to mark a note item as a "decision" so that I can distinguish it from general discussion.
- As a user, I want to mark a note item as an "action item" and assign an owner's name to it so that accountability is clear.
- As a user, I want to mark an action item as "done" or "open" so that I can track its status over time.
- As a user, I want to view a list of all past sessions for a given meeting so that I can review history.
- As a user, I want to search across all my notes and meetings by keyword so that I can quickly find a past decision or action item.
- As a user, all my data must be stored locally on my device with no login required, so that I can start using the app immediately and trust my data stays private.

### Should-have

- As a user, I want to filter action items by owner so that I can see everything assigned to a specific person.
- As a user, I want to filter action items by status (open vs done) so that I can focus on what's outstanding.
- As a user, I want to export a meeting's notes as a plain text or markdown file so that I can share it outside the app.
- As a user, I want to edit or delete a past note entry so that I can correct mistakes.

### Nice-to-have

- As a user, I want to see a dashboard of all open action items across every meeting so that I get a bird's eye view of my commitments.
- As a user, I want to duplicate a meeting's structure (e.g. recurring agenda template) so that I don't have to retype it each time.
- As a user, I want to tag notes with custom labels so that I can organize them beyond just meeting and date.
- As a user, I want a light or dark theme toggle so that I can use the app comfortably in different environments.

## 6. Acceptance Criteria

**Story: Create a named recurring meeting**
- Given the user is on the home screen, when they click "New Meeting" and enter a name, then a new meeting is created and appears in the meeting list.
- Given a meeting name field is left blank, when the user tries to save, then the app shows a validation message and does not create the meeting.
- Given a meeting already exists with the same name, when the user creates another with the identical name, then the app allows it but treats them as separate entries (no forced uniqueness required).

**Story: Add a new dated note entry under a meeting**
- Given a meeting exists, when the user clicks "Add Session" or "New Entry" and enters today's date (or a chosen date), then a new session is created and saved under that meeting.
- Given a session has been created, when the user adds free text notes to it, then those notes are saved and visible when the session is reopened.
- Given the user closes the app without saving, when they reopen it, then any previously saved sessions and notes are still present (data persists locally).

**Story: Mark a note item as a "decision"**
- Given the user is adding or editing a note item, when they select "Decision" as the item type, then the item is visually tagged as a decision in the session view.
- Given a session has one or more items tagged as decisions, when the user views the session, then all decision items are clearly distinguishable from regular notes.

**Story: Mark a note item as an "action item" with an owner**
- Given the user is adding or editing a note item, when they select "Action Item" as the type and enter an owner's name, then the item is saved with that owner attached.
- Given an action item is created without an owner name entered, when the user tries to save, then the app either prompts for an owner or allows it to be saved as "unassigned" (behavior must be consistent and documented).
- Given an action item has an owner, when the user views the session or a filtered list, then the owner's name is displayed next to the item.

**Story: Mark an action item status as done or open**
- Given an action item exists, when the user toggles its status to "Done", then the item visually updates to reflect completion (e.g. checkmark or strikethrough).
- Given an action item is marked "Done", when the user toggles it back, then it returns to "Open" status.
- Given an action item's status changes, when the user reopens the app later, then the status persists as last set.

**Story: View a list of all past sessions for a meeting**
- Given a meeting has two or more sessions, when the user opens that meeting, then all sessions are listed in reverse chronological order (most recent first) with their dates visible.
- Given a meeting has zero sessions, when the user opens that meeting, then an empty state message is shown (e.g. "No sessions yet").

**Story: Search across all notes and meetings by keyword**
- Given the user types a keyword into the search bar, when the keyword matches text in any note, decision, or action item across any meeting, then matching results are displayed with enough context to identify the source meeting and date.
- Given a search keyword matches nothing, when the user submits the search, then a clear "no results found" message is shown.
- Given search results are displayed, when the user clicks a result, then they are taken directly to that specific session.

**Story: All data stored locally with no login required**
- Given a new user opens Recapp for the first time, when the app loads, then no login screen, signup form, or account creation prompt is shown.
- Given the user creates meetings and notes, when they close and reopen the app (or restart their device), then all previously entered data is still present without needing to sign in.
- Given the app is used, when checked, then no data is transmitted to any external server or backend (verifiable via network inspection showing no outbound calls with note content).

## 7. Risks

- Storing all data locally means if the user clears browser data, reinstalls the app, or switches devices, all meeting history could be permanently lost with no backup or recovery option.
- Without cloud sync, small teams who want to share notes must rely on manual export/import or copy-paste, which may feel clunky and limit adoption for team use cases.
- Local-only storage may create a false sense of "it just works forever" until a user hits a storage limit (e.g. browser storage caps) with no warning system in place.
- Search functionality across potentially large volumes of local text notes could become slow if not designed with performance in mind from the start.
- Users may expect features common in competing tools (reminders, calendar integration, AI summaries) and be disappointed by their absence, leading to churn.
- No login means no way to verify or recover a user's identity if they need support, and no way to gather usage analytics without explicit, privacy respecting opt-in mechanisms.
- Data migration or version upgrades to the app could risk corrupting or losing locally stored data if not carefully handled.
- Small teams with multiple people using the app independently for the "same" meeting could end up with fragmented, non-reconciled notes since there is no shared source of truth.

## 8. Success Metrics

**Leading indicators (early signals):**
- Number of meetings created within the first session of use.
- Percentage of sessions where at least one item is tagged as a decision or action item (vs plain untagged notes).
- Number of returning users who log a second session within 14 days.
- Average number of searches performed per active user per week.
- Percentage of action items that get their status changed from "open" to "done" over time (signals real usage, not just note dumping).

**Lagging indicators (final outcomes):**
- Percentage of meetings with a complete, structured record (decisions and action items captured) three months after adoption.
- Average time users report it takes to find a past decision or action item (via periodic survey or in-app feedback prompt).
- Percentage of action items with a named owner and resolved status after 3 months of use.
- User retention rate at 30, 60, and 90 days.
- Self-reported reduction in "we already discussed this" repeat conversations, gathered via periodic in-app survey.