/* Axis — the live canvas.
 *
 * Everything here is progressive enhancement over a page that already works. With
 * this file absent or broken, `#ask-form` posts natively to /ask, the upload form
 * posts to /upload, every card is a link to `/?stage={id}`, and the server renders all
 * of it. That fallback is a hard requirement: the whole single-machine promise is that
 * nothing needs downloading.
 *
 * Hand-written rather than a framework for the same reason the observability library
 * is: a student should be able to read the thing that draws the trace. It is also why
 * there is no build step — this file is served as it is written.
 *
 * WHAT THIS FILE DOES NOT DO, and the reason is the important part:
 *
 * **It does not render the canvas.** It fetches `/canvas` and swaps the HTML in. An
 * earlier version rebuilt the diagram node by node from the step JSON, in parallel with
 * a template doing the same on the server — and the two drifted twice, first over how
 * repeated retrievals were grouped and then over the attributes that give a reloaded run
 * its colours. The cards carry far more than those nodes did, and a drift here would
 * mean a student is shown different numbers live than on reload, in a tool whose entire
 * claim is that the numbers are real.
 *
 * So there is one renderer, on the server, and this file decides *when* to ask for it.
 *
 * EVERYTHING THE CANVAS SHOWS IS MEASURED. This file used to infer the running stage —
 * a step reached the store only when it *completed*, so there was no "started" signal at
 * all, and `markRunning()` marked the next pending card and hoped. A step is now written
 * on entry as well, so which stage is in flight is read from the trace like everything
 * else. The inference is gone, and with it the last place this script decided something
 * about a run.
 */

const POLL_MS = 250;

const form = document.getElementById("ask-form");
const button = document.getElementById("ask-button");
const canvas = document.getElementById("canvas");

// Bail out quietly rather than half-upgrading. A page missing any of these is one this
// script was not written for — the Compare and Trace pages, for instance — and every
// native path still works.
if (form && button && canvas) {
  enhance();
}

wireUpload(document.getElementById("upload-form"));

// Every page, not only the canvas — the raw trace has its own narration controls and
// they had no listener at all, because this used to be called from inside `enhance()`
// and `enhance()` bails on any page without a canvas. So the "Narrated" disclosure on
// the trace page opened and stayed empty from the moment the pages were split.
//
// That is the second time this one feature has been broken by something structural
// rather than by its own logic: before this it pointed at `/api/v1`, which the browser
// cannot authenticate to. Both failures looked identical from the outside — a control
// that opens and does nothing — and neither was visible to a test that called the API
// directly. Hence `test_narration_is_wired_on_the_trace_page`.
wireNarration(document);

// Choosing a run on the Compare page recomputes it, without the button. The button stays
// and is what actually works: a `<select>` plus a submit is the whole mechanism, and this
// only saves a click. Anything that made the selection *depend* on a script would be dead
// on the no-JavaScript path — which is how the narration control above came to be broken
// for two pages without anyone noticing.
wireCompare(document.getElementById("compare-form"));

// Every form that posts natively and spends real money. Each declares its own busy
// label in the markup; this owns the mechanism and nothing else. Called from the
// document, like the two above, so it works on whichever page happens to render one.
wireBusyForms(document);

function wireCompare(compareForm) {
  if (!compareForm) return;
  for (const select of compareForm.querySelectorAll("select")) {
    select.addEventListener("change", () => compareForm.submit());
  }
}

/* Busy state for every form that posts natively and spends real money.
 *
 * **The one enhancement here that does not intercept anything.** Ask and Upload
 * `preventDefault()` and drive the canvas themselves; this lets the native post go
 * through and only marks the form while the browser navigates. That is the whole
 * mechanism, and it is what keeps the no-JavaScript path identical: with this function
 * absent every one of these forms posts exactly as it does with it, one spinner poorer.
 *
 * **Declarative, because the alternative was a list here that kept going stale.** A form
 * opts in with `data-busy-label`, which is also the word it shows while working — the
 * template owns the wording, this owns the behaviour. The previous version knew one
 * selector, `.painpoint__form`, and meanwhile `Load the demo set` and `Summarize` each
 * carried a `.spinner` that nothing ever turned on, and `Clear this corpus` and
 * `Start over` had none at all. Those are among the most expensive clicks in the
 * product: loading the demo set is five paid embedding round trips.
 *
 * Buttons are grouped by their nearest `[data-busy-group]` ancestor, or the document.
 * Submitting one disables the whole group, because a second run while one is in flight
 * is more paid work whose result the pending navigation is about to discard.
 */
function wireBusyForms(root) {
  const forms = [...root.querySelectorAll("form[data-busy-label]")];
  if (!forms.length) return;

  // The resting state, captured before anything touches it. Read back on a bfcache
  // restore below, and it has to come from the page rather than from a constant here:
  // the label would be a second copy of a string the template owns, and a button the
  // server rendered `disabled` — nothing indexed in this corpus, say — must not be
  // switched live by a restore.
  const resting = new Map(
    forms.map((f) => {
      const submit = f.querySelector('button[type="submit"]');
      return [f, {
        label: f.querySelector(".button__label")?.textContent ?? "",
        disabled: submit ? submit.disabled : false,
      }];
    }),
  );

  const peers = (busyForm) => {
    const group = busyForm.closest("[data-busy-group]");
    return group ? forms.filter((f) => f.closest("[data-busy-group]") === group) : [busyForm];
  };

  for (const busyForm of forms) {
    busyForm.addEventListener("submit", () => {
      // `submit` does not fire on a form the browser considers invalid, so a
      // bring-your-own-question card's `required` input cannot strand a spinner on an
      // empty box. Nothing here needs to re-check that.
      if (busyForm.dataset.busy === "true") return;
      busyForm.dataset.busy = "true";
      busyForm.setAttribute("aria-busy", "true");

      const label = busyForm.querySelector(".button__label");
      if (label) label.textContent = busyForm.dataset.busyLabel;

      // Deferred by a tick, and that is not style. Disabling a submit button from
      // inside its own `submit` handler is a long-standing way to cancel the submission
      // in some browsers; letting the event finish dispatching first is what makes this
      // safe. The delay is invisible and the alternative is a button that spins and
      // never posts.
      //
      // The submitting button is disabled too — it must not take a second click — but it
      // does not fade with the others: `[data-busy="true"] button[disabled]` in app.css
      // holds it at full opacity, because fading the button that is showing the spinner
      // is what made the spinner invisible in the first place.
      setTimeout(() => {
        for (const other of peers(busyForm)) {
          const submit = other.querySelector('button[type="submit"]');
          if (submit) submit.disabled = true;
        }
      }, 0);
    });
  }

  // Restored from the back/forward cache, a page comes back exactly as it left — which
  // for a native-post spinner means still spinning, over work that finished, with every
  // button disabled. `pageshow` is the only event that fires in that case; `load` does
  // not.
  window.addEventListener("pageshow", (event) => {
    if (!event.persisted) return;
    for (const busyForm of forms) {
      const was = resting.get(busyForm);
      delete busyForm.dataset.busy;
      busyForm.removeAttribute("aria-busy");
      const label = busyForm.querySelector(".button__label");
      if (label && was) label.textContent = was.label;
      const submit = busyForm.querySelector('button[type="submit"]');
      if (submit && was) submit.disabled = was.disabled;
    }
  });
}

function enhance() {
  form.addEventListener("submit", onAsk);
  for (const radio of document.querySelectorAll('.strategies input[name="strategy"]')) {
    radio.addEventListener("change", () => onSelectStrategy(radio.value));
  }
  wireCanvas();
}

/* ---------------------------------------------------------------- the canvas ---- */

/* Card clicks are intercepted so the diagram swaps instead of the page navigating.
 * Delegated from the wrapper, because everything inside it is replaced wholesale as a
 * run advances and per-card listeners would not survive that. */
function wireCanvas() {
  canvas.addEventListener("click", (event) => {
    if (event.metaKey || event.ctrlKey || event.shiftKey) return;

    const open = event.target.closest("a.card__open, a.siblings__item");
    if (open) {
      event.preventDefault();
      showCanvas(open.dataset.step);
      return;
    }
    // Back to the whole diagram. Nothing expanded is the resting state: every card
    // draws its own data, so the default view is the entire pipeline at once.
    if (event.target.closest("a.card__close")) {
      event.preventDefault();
      showCanvas(null);
    }
  });
}

/* Fetch and swap. `stageId` null means nothing expanded.
 *
 * The address bar is kept in step so a reload lands on the same open card — cheap,
 * and it means the browser's back button walks the stages a student clicked through
 * rather than leaving the page. */
async function showCanvas(stageId) {
  const params = new URLSearchParams();
  if (stageId) params.set("stage", stageId);
  // Which document the indexing track is describing. Carried on every canvas fetch and
  // written back into the address bar, because opening or closing a card must not move
  // the track to a different document — the server's default is the newest, so dropping
  // the parameter is not neutral.
  if (selectedDocument) params.set("document", selectedDocument);
  const query = params.toString();
  try {
    const response = await fetch(query ? `/canvas?${query}` : "/canvas");
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    canvas.innerHTML = await response.text();
    wireNarration(canvas);
    history.replaceState(null, "", query ? `/?${query}` : "/");
  } catch (error) {
    // Every card is still a real link, so the student can navigate; only the in-place
    // swap failed.
    console.error("Axis: could not load the canvas", error);
  }
}

/* Re-fetch while a run is in flight, preserving whatever card is open.
 *
 * Called when a step *completes*, not on every poll: the diagram is replaced wholesale,
 * and doing that four times a second would restart the running card's pulse continuously
 * and make the whole thing flicker. Seven swaps in a run is what this costs, and each one
 * coincides with something actually moving. */
async function refreshCanvas() {
  const open = canvas.querySelector('.card[data-expanded]')?.dataset.step;
  const strategy = selectedStrategy();
  const params = new URLSearchParams();
  if (open) params.set("stage", open);
  if (strategy) params.set("strategy", strategy);
  // The floor for the answering cards while a run is in flight. Without it the server
  // binds the most recent step of each type across the session, so a refresh two
  // seconds into a new question would draw the *previous* question's search, prompt
  // and answer under the new one — plausible, wrong, and now carrying real numbers.
  if (runFloor !== null) params.set("since", String(runFloor));
  if (selectedDocument) params.set("document", selectedDocument);
  try {
    const response = await fetch(`/canvas?${params}`);
    if (!response.ok) return;
    canvas.innerHTML = await response.text();
    wireNarration(canvas);
  } catch (error) {
    console.warn("Axis: could not refresh the canvas", error);
  }
}

/* ---------------------------------------------------------------- the stream ---- */

/* Fed by polling `/trace/state`, not by an SSE stream, and the reason is worth
 * knowing because SSE would be the obvious choice: the Frontend reaches the Backend
 * through `httpx.ASGITransport`, which buffers a response body to completion, so an
 * open-ended stream cannot be proxied through it. Connecting straight to the Backend
 * is not possible either — `EventSource` cannot set the `Authorization` header that
 * route requires.
 *
 * At 250 ms over a 2–8 second run that is eight to thirty requests against an
 * in-process store, each returning about fifty bytes, and it looks the same as
 * streaming. The Backend's SSE endpoint remains the design for the networked topology
 * (System Design Section 6.2). */
// Polling runs as a loop rather than a `setInterval`, so a slow poll delays the next
// one instead of overlapping it. An interval fires whether or not the last tick has
// finished, and two ticks in flight against a store that is being written to is how a
// backlog starts.
let polling = false;
// The sequence number the current run started at, so the answering cards can be floored
// to this run and never show the previous question's numbers. Null when nothing is
// running.
let runFloor = null;
// The last trace state this page drew. The canvas is re-fetched when this moves and at
// no other time: it is replaced wholesale, and re-rendering four times a second would
// restart every animation on it and lose an open card's chunk pager.
let fingerprint = null;
// Which document's indexing the track is showing, read once from the address bar. The
// sidebar's document links are plain navigations, so the server has already resolved the
// selection by the time this runs — this only has to *keep* it across the canvas swaps
// that never reload the page.
let selectedDocument = new URLSearchParams(location.search).get("document");

/* The trace's shape and state, in one small object.
 *
 * `fingerprint` hashes every step's id and status, so it moves when a stage starts as
 * well as when one finishes — which a `seq` watermark structurally cannot see, because
 * a step keeps its `seq` when it goes from running to done. That transition is the
 * whole of what "watch it happen" means here. */
async function traceState() {
  try {
    // `/trace/state`, not `/trace/recent`: the digest alone is about fifty bytes,
    // where the full trace is hundreds of kilobytes after a dozen questions and grows
    // for as long as the session lives. Polling the big one four times a second made
    // each poll slower than the interval between polls, so they overlapped, filled the
    // browser's six connections to this host, and pushed the `/canvas` fetches — the
    // ones that actually redraw the page — behind a queue. The run then appeared to
    // finish in a single jump at the end.
    const response = await fetch("/trace/state");
    if (!response.ok) return null;
    return await response.json();
  } catch {
    return null; // transient; the next tick tries again
  }
}

/* Anchor before a run: make sure there is a session to watch, then remember where the
 * trace stood so this run's cards can be told from the last one's.
 *
 * The session matters more than it looks. It is otherwise created by whichever request
 * first needs one — for a new visitor, the upload itself, whose cookies arrive with its
 * response *after* indexing has finished. Every poll during that first run therefore
 * went out unauthenticated, got the honest empty answer, and left the canvas blank for
 * the one run a student most needs to watch. */
async function anchor() {
  try {
    await fetch("/session", { method: "POST" });
  } catch (error) {
    // Not fatal: the run still happens and the server still renders it afterwards.
    console.warn("Axis: could not open a session to watch", error);
  }
  const state = await traceState();
  fingerprint = state ? state.fingerprint : null;
  return state ? state.max_seq : 0;
}

async function tick() {
  const state = await traceState();
  if (!state || state.fingerprint === fingerprint) return;
  fingerprint = state.fingerprint;
  await refreshCanvas();
}

function startPolling() {
  if (polling) return;
  polling = true;
  (async () => {
    while (polling) {
      await tick();
      await pause(POLL_MS);
    }
  })();
}

function stopPolling() {
  polling = false;
}

function pause(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/* Wait until the trace stops changing.
 *
 * Used after an upload, where the page then navigates: leaving before the last stage
 * has landed would cut off the thing the student was watching. It *watches* the loop
 * above rather than polling itself — two tickers against one store is the overlap this
 * file just stopped doing. Bounded, because a provider that never returns must not
 * leave a spinner turning for ever; the run is still on the canvas either way. */
async function settle(attempts = 60) {
  let stable = 0;
  while (attempts-- > 0 && stable < 3) {
    const before = fingerprint;
    await pause(POLL_MS);
    stable = fingerprint === before ? stable + 1 : 0;
  }
}

/* ------------------------------------------------------------------- asking ---- */

async function onAsk(event) {
  const strategy = selectedStrategy();
  if (!strategy) return; // let the native post handle it

  // The pressed submit button's own name/value. A labelled example question is a
  // `<button name="preset">` inside this form, and `new FormData(form)` omits it — a
  // submitter's value is only included when passed explicitly. Without this, clicking
  // a prediction would post an empty question and the whole set would appear to do
  // nothing under JavaScript while working fine without it.
  const body = new FormData(form, event.submitter);

  event.preventDefault();
  setBusy(true);

  // Everything already recorded belongs to earlier questions or to indexing. Anchoring
  // here is what keeps this run's cards showing only this run.
  runFloor = await anchor();
  resetQueryStages();
  startPolling();

  try {
    const response = await fetch("/ask/fragment", {
      method: "POST",
      body,
      headers: { "X-Requested-With": "axis" },
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);

    // The whole canvas, with the answer open. The server chose that, not this file —
    // see `_run_query`.
    canvas.innerHTML = await response.text();
    wireNarration(canvas);

    const flash = response.headers.get("X-Axis-Flash");
    if (flash) {
      // A refused query — a cap, an unavailable strategy, a provider fault. The canvas
      // keeps whatever it managed to fill, which is the useful part: you can see how
      // far the run got before it stopped.
      showFlash(decodeURIComponent(flash));
    }
  } catch (error) {
    // The answer is what matters, so fall back to the path that definitely works
    // rather than leaving a spinner turning forever.
    console.error("Axis: in-place ask failed, falling back to a full post", error);
    stopPolling();
    form.submit();
    return;
  }

  setBusy(false);
  stopPolling();
  runFloor = null;
}

/* A new question invalidates the previous one's answering cards, but not the indexing
 * ones — those describe documents that are still indexed, and blanking them would
 * suggest asking a question un-indexes your files. */
function resetQueryStages() {
  for (const card of canvas.querySelectorAll(".track--query .card")) {
    card.dataset.state = "pending";
    card.removeAttribute("data-expanded");
  }
}

/* ------------------------------------------------------------------ indexing ---- */

/* Upload used to be a native post plus a 303, so nothing could watch it happen — the
 * four indexing stages ran invisibly and the only evidence was a document appearing in
 * the sidebar with a chunk count. Intercepting it is what makes "watch a document become
 * vectors" possible at all, and it reuses the ask flow's polling unchanged: ingestion
 * steps arrive on the same channel.
 *
 * The native post remains the fallback. With this script absent the redirect still
 * happens and the server renders the completed indexing cards, one round trip later.
 */
function wireUpload(uploadForm) {
  if (!uploadForm) return;
  const submit = uploadForm.querySelector('button[type="submit"]');
  const input = uploadForm.querySelector('input[type="file"]');
  const hint = uploadForm.querySelector(".upload__hint");
  if (!submit || !input) return;

  const sync = () => {
    const files = [...(input.files || [])];
    // Disabled only once this script is running, so the no-JavaScript path keeps a
    // working button. A spinner for a request that returns "no files were included"
    // is worse than no spinner.
    submit.disabled = files.length === 0;
    if (hint) {
      hint.textContent = files.length
        ? files.map((f) => f.name).join(", ")
        : hint.dataset.default || hint.textContent;
    }
  };
  input.addEventListener("change", sync);
  sync();

  uploadForm.addEventListener("submit", (event) => onUpload(event, uploadForm, submit));
}

async function onUpload(event, uploadForm, submit) {
  // Without the canvas there is nothing to watch, so the native post is strictly better.
  if (!canvas) return;

  event.preventDefault();
  uploadForm.dataset.busy = "true";
  uploadForm.setAttribute("aria-busy", "true");
  submit.disabled = true;
  const label = submit.querySelector(".button__label");
  if (label) label.textContent = "Indexing";

  // Watch the document being uploaded, not the one that was selected. Holding a
  // selection here would leave the indexing track frozen on an older document while the
  // new one parsed, chunked and embedded behind it — the one run a class most needs to
  // see. The navigation at the end lands on `/`, which resolves to the newest anyway.
  selectedDocument = null;

  await anchor();
  startPolling();

  try {
    const response = await fetch(uploadForm.action, {
      method: "POST",
      body: new FormData(uploadForm),
      headers: { "X-Requested-With": "axis" },
      // The server answers a form post with a 303 to `/`. Following it would fetch a
      // whole page and throw it away; the canvas is refreshed from the trace instead.
      redirect: "manual",
    });
    if (response.type !== "opaqueredirect" && !response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    // Wait for the trace to stop moving before navigating. This used to be a fixed
    // 1.6-second timer, which was already a guess and becomes a wrong one the moment
    // slow motion is on — the reload would land in the middle of the run a class was
    // watching.
    await settle();
    // The sidebar lists the documents and is server-rendered, so it needs the round
    // trip this flow avoided. Deferred until the indexing track has been watched.
    window.location.assign("/");
  } catch (error) {
    console.error("Axis: in-place upload failed, falling back to a full post", error);
    stopPolling();
    uploadForm.submit();
    return;
  }

  stopPolling();
}

/* ------------------------------------------------------------------- chrome ---- */

function selectedStrategy() {
  const checked = document.querySelector('.strategies input[name="strategy"]:checked');
  return checked ? checked.value : null;
}

/* The identity colour for the whole page. Which cards the canvas shows is pure CSS via
 * `body:has()`; this is the one part CSS cannot do, because it sets a value rather than
 * toggling a rule. */
function onSelectStrategy(strategy) {
  document.body.dataset.strategy = strategy;
  if (form.dataset.busy === "true") return; // never clobber a run in flight
  refreshCanvas();
}

function setBusy(busy) {
  button.disabled = busy;
  form.setAttribute("aria-busy", String(busy));
  form.dataset.busy = String(busy);
  button.querySelector(".button__label").textContent = busy ? "Running" : "Ask";
}

function showFlash(message) {
  const banner = document.createElement("div");
  banner.className = "banner banner--warn";
  banner.innerHTML = `<strong></strong>`;
  banner.querySelector("strong").textContent = message;
  (canvas || document.body).prepend(banner);
}

/* Narration, per step, generated on first open and cached server-side. */
function wireNarration(root) {
  if (!root) return;
  for (const box of root.querySelectorAll(".card__narrate[data-step]")) {
    box.addEventListener("toggle", onNarrate, { once: true });
  }
  for (const summary of root.querySelectorAll("[data-narrate]")) {
    summary.addEventListener("click", onLegacyNarrate, { once: true });
  }
}

async function onNarrate(event) {
  const box = event.currentTarget;
  if (!box.open) return;
  const target = box.querySelector(".card__narration");
  if (!target || target.textContent.trim()) return;

  target.textContent = "Explaining…";
  try {
    const response = await fetch(`/narrate/${encodeURIComponent(box.dataset.step)}`, {
      method: "POST",
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    target.textContent = (await response.json()).narration;
  } catch (error) {
    console.error("Axis: narration failed", error);
    target.textContent = "Could not generate an explanation for this step.";
  }
}

/* The raw trace page still renders its own cards with their own narrate control. */
async function onLegacyNarrate(event) {
  const summary = event.currentTarget;
  const target = summary.closest(".step__views")?.querySelector(".step__narration");
  if (!target || target.dataset.loaded) return;

  target.textContent = "Explaining…";
  try {
    const response = await fetch(summary.dataset.narrate, { method: "POST" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    target.textContent = (await response.json()).narration;
    target.dataset.loaded = "true";
  } catch (error) {
    console.error("Axis: narration failed", error);
    target.textContent = "Could not generate an explanation for this step.";
  }
}
