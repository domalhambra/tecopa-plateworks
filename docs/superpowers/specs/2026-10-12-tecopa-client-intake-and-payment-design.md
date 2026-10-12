# Tecopa: how a client sends tracks and pays

**Status:** Being built. Designed with Dom in a brainstorming session on 2026-10-12. The build started the same day. In `tecopa-plateworks`, section 5 and this repo's parts of sections 9 and 10 are built: `order new`, the preview email, the prices file and the tool's entry. The section "In this repo, what the build chose" at the end lists the choices the design left open. The other three repos build their parts in their own repos.
**Governs:** `plateworks-lab-intake` (a new path and the Stripe routing), `tecopa-plateworks` (one command, the preview email, the prices file), `plateworks-art-prints` (the Payment Links list), and in `22 Plateworks Blog`: `scripts/ghost-tecopa-pages.mjs` (the three Tecopa pages).
**Changes:** `tecopa-plateworks` `docs/superpowers/specs/2026-09-24-order-pipeline-design.md` ("Out of scope" listed a web order form and payment) and `2026-10-11-print-sizes-panel-sets-and-size-preview-design.md` (decision 12 left this design for later). `plateworks-lab-intake` D16 (a Payment Link sale with a `pw_sku` goes to the Art Prints tab).

## 1. Goal

A client gives tracks. Tecopa Plateworks makes the map and shows it at each size that suits it. The client chooses a size and pays. Dom makes the proof, the client approves it, and Dom prints and ships.

Today the client sends an email with attachments to `lab@plateworks.org`, and pays an invoice after the proof. This design replaces the email with a form and an upload, and moves the payment to the size preview. It adds no new service: the form, the upload, the order log and the payment use what the Photo Lab uses.

## 2. Decisions (Dom, 2026-10-12)

| # | Decision |
|---|---|
| 1 | The client pays after the size preview and before the full proof. |
| 2 | The preview email has one Stripe Payment Link for each offered size. |
| 3 | The client can ask for a full refund until the client approves the proof. Nothing prints before the approval. One round of changes is free, as today. |
| 4 | An order starts with a short Tecopa form. The upload page follows in the same visit. |
| 5 | The Tecopa form posts to a new path on the Lab intake's Netlify site. It is not a second site, and it does not use the Lab's own order code. |
| 6 | A set has a public price and a Payment Link: two panels $149, three panels $189. Next-year prices: $119 and $159. |
| 7 | Shipping: $8 for 11 × 17, $12 for 17 × 22, $16 for a set. The digital poster ships nothing. |
| 8 | Tracks and photos are deleted 90 days after delivery. A client can ask Dom to hold them for a next-year order. |
| 9 | Member codes are off on the Tecopa links. A member gets the shipping back through member links instead (changed 2026-10-12, below). |
| 10 | The three rules of the Lab intake hold here. Nothing sends an email by itself. Nothing charges anyone by itself. Dom reads each request before anything goes out. |

## 3. The order, step by step

| Step | Who | What happens |
|---|---|---|
| 1 | Client | Opens "Build your poster" and starts the form: name, email, poster title, notes, and if this is a first poster. |
| 2 | Intake | Makes the order number, the Dropbox job folder, the upload link, the row in the order log, and `order.md` with the drafted emails. |
| 3 | Client | Lands on the upload page and uploads tracks and photos. |
| 4 | Dom | Gets Tally's email for the request and Dropbox's email for the files. |
| 5 | Dom | Runs `order new`, then `order preview`, on the Mac. |
| 6 | Dom | Sends the preview email from HEY: the PDF, and a Payment Link for each offered size. |
| 7 | Client | Chooses a size and pays on Stripe's page. |
| 8 | Intake | Marks the row paid and writes the size. |
| 9 | Dom | Types the size in `order.toml`, runs Prepare, makes the proof in the studio, and sends it. |
| 10 | Client | Approves the proof, asks for one round of changes, or asks for the refund. |
| 11 | Dom | Renders the final, prints, and ships on a Tuesday or Friday. |
| 12 | Dom | Deletes the files 90 days after delivery, unless the client asked for a hold. |

The email address stays on the pages for questions. The email with attachments is no longer the way to order.

## 4. The intake side (`plateworks-lab-intake`)

### 4.1 The form

A second Tally form, "Build your poster". Its questions:

- Name. Email. Poster title. "Anything I should know".
- "Have you ordered a Tecopa poster before?" Yes selects the next-year prices.
- "Are you a member at plateworks.org?" and, on Yes, "Membership email, if different". Added 2026-10-12 (decision 9).

The form does not ask for a size. The size preview settles it. On submit, Tally sends the client to `/upload` with the submission ID, as the Lab form does.

### 4.2 The path `/tecopa`

A new function. It checks Tally's signature with the Tecopa form's own secret, and it ignores any other form. It then does five steps, in this order. Each step is safe to repeat, because Tally retries a delivery.

1. Append a row to the tab `Tecopa` of the order log, with the status `creating`.
2. Compute the order number from the rows above its own: `TP-YY-NNN`, for example `TP-26-001`.
3. Make the job folder `Tecopa/TP-26-001 Smith/01_received` in Dropbox.
4. Make a Dropbox file request into `01_received`. The upload link is for this order only.
5. Write `order.md` in the job folder, then set the row's status to `new-request`.

Rules:

- The Tecopa logic is one new module. `lib/order.mjs`, the Lab's order code, does not change.
- The job folder is outside `Orders/`, and its file is `order.md`, not `ticket.md`. The Photoshop scripts read `ticket.md` in `Orders/`, so they never read a map order. A free check uses the same protection.
- The submission ID is the key that stops a second order from a retry.
- A failure to make the upload link does not stop the order. `order.md` says to make the link by hand.
- The logs hold IDs and counts only. No name, email or link goes to Netlify's logs.
- New settings in Netlify: the Tecopa form's ID and its signing secret. No secret is in a repo or in chat.

### 4.3 `order.md`

Front matter: the order number, the date, the client's name and email, the title, the first-poster flag, `member: claimed` or `member: no`, the upload link. Then the client's notes and these drafted emails. All have one subject, so that HEY keeps one thread for each order:

- The upload reminder, for a client who closed the upload page.
- Payment received.
- The proof.
- The 72-hour nudge for a proof with no answer.
- Shipped, or the file sent for a digital poster.
- The follow-up. It states the date on which the files are deleted, and that a reply holds them for a next-year order.

The preview email is not in `order.md`. The sizes are not known at intake. Section 5.2 makes it.

### 4.4 The upload page

`/upload` finds a submission in the Lab's tab today. It also looks in the tab `Tecopa`. For a map order the page shows the order number and the upload link, and says:

- Upload GPX, KML or KMZ files, and any photos for the map.
- The link works with no Dropbox account.
- What comes next: the map at each size by email, with the prices.
- From May to November Dom is on fire assignments, and the preview comes when he is back.

The page still shows only a `dropbox.com/request/` link and the order number.

### 4.5 The tab `Tecopa`

One row for each map order. Who fills each column:

| Filled by | Columns |
|---|---|
| The intake | `order_id`, `received`, `status`, `client`, `email`, `title`, `returning`, `flags`, `folder`, `upload_link`, `tally_submission` |
| Stripe, through `/stripe` | `size`, `order_value`, `shipping_charged`, `paid`, `stripe_payment`, `stripe_invoice`, and `status` on a full refund |
| Dom | `files_received`, `preview_sent`, `proof_sent`, `approved`, `shipped`, `tracking`, `delivered`, `hold_files`, `deleted`, `followup_sent`, `notes` |
| A formula | `delete_after`: `delivered` plus 90 days, and blank when `hold_files` is filled |

The Ship list tab gets a third block: map orders that are paid, approved and not shipped. It also gets a list of orders whose `delete_after` is past and whose `deleted` is blank. `npm run sheet:ship-list` builds both, as it builds the two blocks that exist.

## 5. The Mac side (`tecopa-plateworks`)

### 5.1 `order new`

`scripts/order.py new <order number>`, and `tecopa order new` in the tool.

- It finds the job folder in the Dropbox folder that syncs to the Mac: `~/Dropbox/Apps/Plateworks Lab/Tecopa/`. The setting `TECOPA_INTAKE_DIR` names another place.
- It copies each file of `01_received` into `in/` of a new order folder, `~/Tecopa Orders/TP-26-001-smith/`. It never moves a file and never writes to Dropbox.
- It writes `order.toml` with the title, the order number and the first-poster flag, read from `order.md`. It writes no size.
- It reports what it copied: tracks, photos, and files of a type it does not know.
- A second run adds the files that arrived later. It replaces no file and does not change `order.toml`.

The files come from a stranger. The command cleans each file name, refuses a name that leaves the order folder, refuses a file of more than 200 MB, and opens no file. It reads `order.md` as text and trusts none of its values. A title or a name with unsafe characters is cleaned or refused. That happens before the value becomes a folder name or a line of `order.toml`. The engine's own readers open the tracks later, as they do for an order today.

A file that Dropbox has not downloaded yet must not be copied as an empty file. The command checks each copy against the size that Dropbox reports, and stops with a message when a file is not on the disk.

### 5.2 The preview email

`order preview` already knows which sizes it offers and their prices. It also writes `out/preview/email.txt`:

- One line for each offered size: the name, the price, the shipping, and the Payment Link.
- A last line for the digital poster.
- The refund sentence of decision 3, and the note that a set is shown with a 2 in gap and can have 0 or 4.

Each link ends with `?client_reference_id=<order number>`. Stripe returns that value with the sale, and that is how a payment names its order. The client's email address is not in the link: the order number is enough, and less personal data travels in a URL. The Lab's link for the Starter Set also carries the email. This design does not.

An order with `returning = true` gets the next-year links and prices.

An order with `member = true` gets the member links of each print size: the same price with no shipping, and no code to enter. The digital poster's link is the same for everyone.

### Members (Dom, 2026-10-12)

Dom decided that a member gets the Tecopa shipping back. A Stripe coupon takes money off products, never shipping, and a shared code travels, so the form asks instead. A Yes writes `member: claimed` to `order.md` and the Tecopa tab, with a flag naming the email to check. `order new` writes `member = true` and its report says to check Ghost; Dom checks before the preview email goes out, and sets `member = false` when the client is not one. The intake never reads Ghost. Each print size gains two links with $0 shipping, `tecopa-<size>-member` and `tecopa-<size>-next-member`: eight links, at the same prices. A member link paid on an order not marked member fills the row and goes on Needs attention (intake D31). When real shipping costs are known, a checkout made for each order can replace the links.

### 5.3 The prices file

`config/sizes.toml` holds the names and the first-poster prices of the four print sizes today, and no price for a set. It gains:

- The set prices of decision 6.
- For each size: the next-year price, the shipping charge, the first-poster link and the next-year link.
- A row for the digital poster, which is not a sheet size: $39, next year $25, no shipping, its two links.

A Payment Link is a public address, so it can be in this public repo. The file stays strict: a wrong key or a wrong type stops the preview before it builds anything. A test holds each price in the file equal to the price on the live page, as `tests/test_sizes.py` does for the two single sheets now.

### 5.4 After the payment

The Mac holds no credential for the order log or for Stripe, and this design gives it none. Dom reads the size from Stripe's email or from the row, types `size` in `order.toml`, and runs Prepare. The preview's report already prints the lines to paste for each size.

## 6. Payment

### 6.1 The links (`plateworks-art-prints`)

The `products` list of `payment-links.json` holds items outside the Art Print grid. `tecopa-digital` is there and live since 2026-10-12. This design adds nine entries and changes that one.

| Product | sku, first poster | First poster | sku, next year | Next year | Shipping |
|---|---|---|---|---|---|
| 11 × 17 in | `tecopa-11x17` | $69 | `tecopa-11x17-next` | $59 | $8, the rate `flat` |
| 17 × 22 in | `tecopa-17x22` | $99 | `tecopa-17x22-next` | $69 | $12, a new rate |
| Two panels | `tecopa-two` | $149 | `tecopa-two-next` | $119 | $16, the rate `set` |
| Three panels | `tecopa-three` | $189 | `tecopa-three-next` | $159 | $16, the rate `set` |
| Digital poster | `tecopa-digital` | $39 | `tecopa-digital-next` | $25 | none |

- US addresses only, as every link in the list. Tax is automatic, as for every link.
- No code box (decision 9). Each print size also has two member links, `-member` and `-next-member`, at the same prices with no shipping rate (decision 9, changed 2026-10-12).
- No limit on the number of payments. A map is not a limited run.
- The checkout text of each link states decision 3. The text of `tecopa-digital` says "the poster you approved" and "the email address you sent your track from" today. Both phrases change: the client now pays before the proof and no longer sends tracks by email.
- Dom runs the links script with `--apply`, on his typed approval, as for every change to the links.

### 6.2 `/stripe`

The function checks Stripe's signature and holds no key that can charge. A checkout whose `pw_sku` starts with `tecopa-` is a map sale. It never goes to the Art Prints tab, so it never takes an edition number. That changes D16 for these skus, and it moves the sales of `tecopa-digital`, which go to the Art Prints tab today.

| Event | Result |
|---|---|
| A paid map link with an order number that is in the tab `Tecopa` | The row gets `paid` (the date), `size` (from the sku), `order_value`, `shipping_charged` and `stripe_payment`. |
| A paid map link with no order number, or with a number that no row has | One row on the Needs attention tab (D25). |
| A second paid link for an order that is already paid | The row is not changed. One row on the Needs attention tab. |
| A full refund of a map payment | The row's `status` becomes `refunded`, with a dated note. |
| A part refund | A dated note. The status stays. |
| A paid invoice that names a `TP-` order | The row gets `paid` and `stripe_invoice`, as a Lab order does. |

An order number selects its tab by its prefix: `TP` is the tab `Tecopa`, and any other prefix is the Lab's tab. Each result is safe to repeat. A row that is already paid or refunded is left alone. The Needs attention tab holds one row for each Stripe object.

### 6.3 The invoice as the fallback

An address outside the US, a pickup, or any order that no link fits gets a Stripe invoice by hand, with the order number on it. `/stripe` marks it paid as in the table.

## 7. The pages (`22 Plateworks Blog`, `scripts/ghost-tecopa-pages.mjs`)

| Page | Change |
|---|---|
| Landing, `/tecopa/` | "Email me your tracks" becomes the start of an order. The price tables gain the two sets, with their shipping. "You pay after you've seen your poster and said yes" becomes: you pay after you see your map at each size. You can have a full refund until you approve the proof. The answer to "What happens after I email my tracks?" is written again for the new steps. |
| Order page, `/tecopa-build/` | The email card becomes a Start button that opens the form. The steps become: gather your tracks, pick your photos, start your order and upload, see your sizes, pay, see the proof and say yes. |
| Privacy, `/tecopa-privacy-policy/` | It names what each service holds: Tally (the form's answers), Dropbox (the tracks and photos), Google Sheets (the order record: name, email, what was bought, dates), Stripe (the payment). The LegalZoom sentence goes. It states decision 8. The tracks and photos are deleted 90 days after delivery. A reply holds them for a next-year order. An email deletes them sooner. It says which records stay: the order record and Stripe's payment record. |

Rules:

- Every claim on a marketing page has a test against the live pages, in `tecopa-plateworks` `tests/test_marketing_page.py`. Each new claim gets one: the set prices, the refund sentence, the 90 days. Each claim that goes loses its test: the email order, the LegalZoom sentence.
- The privacy page states only what happens. Section 10 lists two facts to check before it states a number.
- The season sentence stays as it is.
- Copy that a customer reads follows the Tecopa customer profile and the voice canon, not this document's style.

## 8. Failures

| Case | Result |
|---|---|
| The upload link cannot be made | The order is made. `order.md` says to make the link by hand. |
| A form with no upload | The row stays `new-request`. The reminder is drafted in `order.md`. |
| Files that are not tracks | `order new` lists them. Dom writes to the client. No payment is asked. |
| Tracks outside the lower 48, or a preview that stops | The preview says why. Dom writes to the client. No payment is asked. |
| The client pays for a size that the preview did not offer | The row shows the size. Dom resolves it by email, or with a refund. |
| The client pays two times | The second payment is on the Needs attention tab. Dom refunds it or makes a second print. |
| A paid order with no approval | The 72-hour nudge. Nothing prints. A refund on request. |
| Dom is on a fire assignment | No client can pay unseen, because only Dom sends the preview email. The pages and the upload page say that the preview waits. |

## 9. Tests

- `plateworks-lab-intake`, `npm test`: the Tecopa module (the order from the form's answers, the folder name, `order.md`), the order numbers of two orders that arrive together, a retry at each step, the upload page for a map order, each row of the table in 6.2, and one end-to-end run of `/tecopa` against the pretend Dropbox and Sheet. A test proves that a Lab order and a free check are unchanged.
- `tecopa-plateworks`: `order new` with hostile file names, a file of more than 200 MB, a file not on the disk, a second run, and a hostile `order.md`. The email text: a link for each offered size and for no other, the order number in each link, no email address in a link, the next-year links for a returning client. The strict reading of the new keys of `config/sizes.toml`. The tool's new entry.
- The live tests of the pages, after the pages change.
- The last check is one real order by Dom: the form, an upload, the preview, a real payment, the row marked paid, a full refund, the row marked refunded.

## 10. Order of work, and what to check first

1. The Payment Links and the prices file. The links exist before any code needs them.
2. The intake: the module, `/tecopa`, the upload page, the tab, the Stripe routing, the Ship list block.
3. The Mac: `order new`, the email, the tool's entry, the docs.
4. Dom's hands: the Tally form, the two settings in Netlify, the links script with `--apply`.
5. The one real order of section 9.
6. The pages, last. Until they change, a client still orders by email, so Dom chooses the day. The Now list holds new systems until its review on 2026-10-21. This design reuses the Lab's parts, and the page change can wait for that review.

The plan checks these before it fixes a detail:

- How long Dropbox keeps a deleted file on Dom's plan. The privacy page states that number or none.
- If Tally keeps the form's answers after the order, and how they are deleted. The 90 days of decision 8 are for the tracks and photos. The plan says if the form's answers follow the same rule.
- If `order.toml` refuses an unknown key today, for the two new keys.
- The Tally redirect and the signing secret for a second form on one account.
- Where the order log is. A plan of 2026-10-12 to move the order log from the Google Sheet to Notion waits for Dom's decisions. This spec builds on the Sheet. If the move is decided first, sections 4.5 and 6.2 follow the new log, and the rest does not change.

Documents to change with the build: the docs of each of the four repos, with a row that points to this spec, and the Tecopa pages of the Order Desk Manual, which describe the order by email.

## 11. Not in this spec

- `order finish`, the TIFF and the customer package. A map order ends at the engine's final, as today.
- An email that a program sends. A charge that a program makes.
- Links for addresses outside the US.
- An order by chat. Photos in the size preview.
- A change to the Lab's form, its order code or its ticket.

## 12. Open, for Dom

1. Which file does a digital-poster client get? The preview shows print sizes. Proposed: the 17 × 22 in file, unless the client names another offered size.
2. A next-year order needs the files. Proposed: the follow-up email asks, and a yes fills `hold_files`. With no answer, the files are deleted on the date.

## In this repo, what the build chose

Written by the build of section 5, 2026-10-12. The sections above are the design as it was written on 2026-10-12.

| Question | What the build did | Where |
|---|---|---|
| Does `order.toml` refuse an unknown key? (section 10) | No. Before this build the reader took the keys it knew and ignored any other key, so a new key was never refused, and a misspelled key was silently dropped. The reader now reads each key of the intake on purpose and checks it: `order_number` (`TP-YY-NNN`, ASCII digits), `returning` (true or false), `client` (at most 80 characters) and `email` (an address). It still ignores a key it does not know. | `app/order.py`, `load`; `tests/test_order.py` |
| The names of the keys | `order_number` and `returning`, as section 5.2 names `returning`. `order new` also writes `client` and `email` when `order.md` has them: the preview email needs a greeting and a To line, and section 5.1 named only the title, the number and the flag. | `app/ordernew.py` |
| The digital poster in `config/sizes.toml` | A `[[size]]` row with `key = "digital"`, the same fields as a size and no `shipping`. The PDF never shows it. The row may be missing from the file: then the preview writes no email and names it. | `app/sizes.py` |
| A Payment Link not made yet | `link` and `next_link` are optional. A link that is there must be `https://buy.stripe.com/` and an id, with no query. With a link missing, the preview writes no email and its report names each missing link. The links script ran with `--apply` on 2026-10-12, and all ten links are in the file. | `config/sizes.toml`; `app/orderemail.py` |
| The PDF of a returning client | It shows the next-year prices, as the email does, so the two never quote two prices for one size. | `app/orderpreview.py`, `preview` |
| The name of the order folder | The order number and the client's part of the job folder's name, cleaned to `a-z`, `0-9` and `-`: `TP-26-001 Smith` becomes `TP-26-001-smith`. A later run finds the folder again by its number, also after Dom renames it. | `app/ordernew.py` |
| A title or a `returning` that is wrong in `order.md` | An empty or long title is written as it is, with a warning: the preview stops on it with its own reason, and Dom edits `order.toml`. A `returning` that is not yes or no, or an `order_id` that is not the number asked for, stops the run before any copy: the first decides the price. | `app/ordernew.py` |
| A file the run refuses | A name that cleans to nothing, a link, a folder, a file over 200 MB (200,000,000 bytes) and a file whose cleaned name is in `in/` already with another size are not copied, and the report names each one. The other files are copied. A file not on the disk stops the whole run, before any copy. | `app/ordernew.py` |
| A file not on the disk | Each file is checked before any copy: the macOS dataless flag, or a size with no block on the disk, stops the run. Each copy's byte count must equal the size Dropbox reports, or the copy is removed and the run stops. | `app/ordernew.py`, `not_downloaded`, `_copy` |
| A member (decision 9, changed) | `config/sizes.toml` gains `member_link` and `member_next_link` on the print sizes, both optional, and the digital row refuses them. `order new` reads `member: claimed` (or `yes`) from `order.md` and writes `member = true`; `no` or no line writes nothing, and any other answer writes nothing with a warning. With `member = true` and a member link missing for an offered size, the preview writes no email and names the link. The preview's report says to check Ghost. | `app/sizes.py`, `app/ordernew.py`, `app/orderemail.py` |
| `tecopa order new` | It runs the script in the call, as `plate install` does, and returns the report. It is not a tracked run: it copies files and reads no network. | `tools/tecopa/Sources/TecopaKit/Orders.swift` |
| The set prices on the live pages | The pages do not show the set prices, next year's set prices or shipping yet (section 7 changes them last). `tests/test_sizes.py` holds each price that a page shows to the page, and names the others in `NOT_ON_THE_PAGES_YET`. | `tests/test_sizes.py` |
