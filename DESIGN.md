---
name: KPI Outbound Voicebot POC
description: An operator console that makes placing a bot call feel as simple as making one on a phone.
colors:
  kpi-blue: "#2c67c6"
  kpi-blue-press: "#2457aa"
  kpi-blue-tint: "#eaf1fc"
  kpi-navy: "#13315f"
  kpi-navy-2: "#1c3f78"
  kpi-sky: "#56bed6"
  ground: "#f5f6f8"
  surface: "#ffffff"
  surface-2: "#f9fafb"
  fill: "#eef0f4"
  separator: "rgba(19, 49, 95, 0.12)"
  separator-strong: "rgba(19, 49, 95, 0.2)"
  ink: "#1b2333"
  ink-2: "#566074"
  ink-3: "#5d6677"
  good: "#18803a"
  good-bg: "#e6f4ea"
  warn: "#9a5600"
  warn-bg: "#fff2df"
  bad: "#c0161c"
  bad-bg: "#fdecec"
typography:
  display:
    fontFamily: "Noto Sans Thai, Noto Sans, -apple-system, BlinkMacSystemFont, Segoe UI, system-ui, sans-serif"
    fontSize: "2rem"
    fontWeight: 700
    lineHeight: 1.2
    letterSpacing: "-0.01em"
  headline:
    fontFamily: "Noto Sans Thai, Noto Sans, -apple-system, BlinkMacSystemFont, Segoe UI, system-ui, sans-serif"
    fontSize: "1.45rem"
    fontWeight: 600
    lineHeight: 1.25
  timer:
    fontFamily: "Noto Sans Thai, Noto Sans, -apple-system, BlinkMacSystemFont, Segoe UI, system-ui, sans-serif"
    fontSize: "2rem"
    fontWeight: 300
    lineHeight: 1
    letterSpacing: "0.01em"
    fontFeature: "tnum"
  title:
    fontFamily: "Noto Sans Thai, Noto Sans, -apple-system, BlinkMacSystemFont, Segoe UI, system-ui, sans-serif"
    fontSize: "1.05rem"
    fontWeight: 600
    lineHeight: 1.4
  body:
    fontFamily: "Noto Sans Thai, Noto Sans, -apple-system, BlinkMacSystemFont, Segoe UI, system-ui, sans-serif"
    fontSize: "1rem"
    fontWeight: 400
    lineHeight: 1.55
  spoken:
    fontFamily: "Noto Sans Thai Looped, Noto Sans Thai, system-ui, sans-serif"
    fontSize: "0.95rem"
    fontWeight: 400
    lineHeight: 1.55
  label:
    fontFamily: "Noto Sans Thai, Noto Sans, -apple-system, BlinkMacSystemFont, Segoe UI, system-ui, sans-serif"
    fontSize: "0.85rem"
    fontWeight: 600
    lineHeight: 1.4
  caption:
    fontFamily: "Noto Sans Thai, Noto Sans, -apple-system, BlinkMacSystemFont, Segoe UI, system-ui, sans-serif"
    fontSize: "0.82rem"
    fontWeight: 400
    lineHeight: 1.45
rounded:
  control: "12px"
  inner: "0.7rem"
  bubble: "1.1rem"
  group: "18px"
  pill: "999px"
spacing:
  xs: "0.25rem"
  sm: "0.5rem"
  md: "0.75rem"
  lg: "1rem"
  xl: "1.25rem"
  section: "1.75rem"
components:
  button-primary:
    backgroundColor: "{colors.kpi-blue}"
    textColor: "{colors.surface}"
    rounded: "{rounded.pill}"
    padding: "0.55rem 1.1rem"
  button-primary-hover:
    backgroundColor: "{colors.kpi-blue-press}"
  button-primary-lg:
    backgroundColor: "{colors.kpi-blue}"
    textColor: "{colors.surface}"
    rounded: "{rounded.pill}"
    padding: "0.9rem 1.5rem"
  button-tinted:
    backgroundColor: "{colors.kpi-blue-tint}"
    textColor: "{colors.kpi-blue-press}"
    rounded: "{rounded.pill}"
    padding: "0.55rem 1.1rem"
  button-plain:
    textColor: "{colors.kpi-blue}"
    rounded: "{rounded.pill}"
    padding: "0.55rem 0.6rem"
  button-plain-hover:
    backgroundColor: "{colors.kpi-blue-tint}"
  button-danger:
    backgroundColor: "{colors.bad-bg}"
    textColor: "{colors.bad}"
    rounded: "{rounded.pill}"
    padding: "0.55rem 1.1rem"
  group:
    backgroundColor: "{colors.surface}"
    rounded: "{rounded.group}"
  group-row:
    backgroundColor: "{colors.surface}"
    padding: "0.6rem 1rem"
    height: "3.25rem"
  tile:
    backgroundColor: "{colors.surface}"
    rounded: "{rounded.group}"
    padding: "1rem 1.1rem 1.1rem"
  segmented:
    backgroundColor: "{colors.fill}"
    rounded: "{rounded.inner}"
    padding: "0.2rem"
  segmented-selected:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
  input-control:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "0.6rem 0.8rem"
  pill-good:
    backgroundColor: "{colors.good-bg}"
    textColor: "{colors.good}"
    rounded: "{rounded.pill}"
    padding: "0.1rem 0.6rem"
  pill-warn:
    backgroundColor: "{colors.warn-bg}"
    textColor: "{colors.warn}"
    rounded: "{rounded.pill}"
    padding: "0.1rem 0.6rem"
  pill-bad:
    backgroundColor: "{colors.bad-bg}"
    textColor: "{colors.bad}"
    rounded: "{rounded.pill}"
    padding: "0.1rem 0.6rem"
  pill-neutral:
    backgroundColor: "{colors.fill}"
    textColor: "{colors.ink-2}"
    rounded: "{rounded.pill}"
    padding: "0.1rem 0.6rem"
  alert-info:
    backgroundColor: "{colors.kpi-blue-tint}"
    textColor: "{colors.kpi-navy}"
    rounded: "{rounded.control}"
    padding: "0.7rem 0.9rem"
  call-head:
    backgroundColor: "{colors.kpi-navy}"
    textColor: "{colors.surface}"
    rounded: "{rounded.group}"
    padding: "1.4rem 1.5rem 1.25rem"
  bubble-bot:
    backgroundColor: "{colors.fill}"
    textColor: "{colors.ink}"
    typography: "{typography.spoken}"
    rounded: "{rounded.bubble}"
    padding: "0.55rem 0.85rem"
  bubble-customer:
    backgroundColor: "{colors.kpi-blue}"
    textColor: "{colors.surface}"
    typography: "{typography.spoken}"
    rounded: "{rounded.bubble}"
    padding: "0.55rem 0.85rem"
---

# Design System: KPI Outbound Voicebot POC

## Overview

**Creative North Star: "The Calm Phone Call", in Liquid Glass**

Since 8 Oct 2026 the console wears Apple-style Liquid Glass (prototype A, chosen by the user and refined from Inspo references: Bevel's floating glass in a high-key white void, Supaste's frosted dark panels, Copilot's floating composer). Every group, tile, panel and bar is clear glass over a quiet lit field, in a light and a dark appearance. The structure below (one task per screen, grouped lists, one pill action) is unchanged.

The North Star has been renamed from "The Calm Call Desk" to fit what was built. The calm stays, but the desk layout of form, panels and a table on one screen is gone. In its place is the idiom of a phone's Settings and Phone apps. Each screen has one task. Inputs sit in white inset groups with hairline separators on a cool grey ground. One pill button leads to the next step. While a call is live, it looks like a phone call: a navy header with the person's name, a timer and live status, a segmented progress strip for the script, and message bubbles below. The user's direction for this world is "production grade, professional, minimal yet elegance like Apple's design" for non-technical Thai contact-center operators.

The user previously asked for components that are "tactile and confident", and the build keeps that through restraint rather than weight. Hit areas are generous (rows at least 3.25rem tall), and a press visibly scales the control down. Selection is always clear: a solid blue check, a blue tile border, or a white segment lifted out of a grey track. KPI blue never appears without a reason. It marks only the action and the current selection, so the eye always lands on the next step. The whole console scales with the viewport (root font `clamp(15px, 0.35vw + 12.5px, 19px)`, with every size in rem), so the same layout stays legible on a phone, a laptop or a projector.

KPI appears as the official full-colour logo (`apps/web/public/brand/kpi-logo.svg`, from kpi.co.th, approved by the PM on 8 Oct 2026). It sits at 2.4rem tall in the top bar, followed by a hairline divider and "Voicebot". On navy it sits on a white plate (0.8rem corners), because KPI blue alone has too little contrast there. Mock data always carries an amber MOCK pill.

**Key Characteristics:**
- Cool grouped-grey ground with white inset groups, 18px corners and inset hairline separators.
- One accent with one job: KPI blue for action and selection only. Navy belongs to the live call. Sky marks the current script step.
- Large left-aligned page titles, sentence-case group headers above each group, and tabular numerals wherever a number is shown.
- One family of authored line icons (1.75 stroke, round caps). No emoji.
- Conversation text is set in the looped Thai face. Interface text is set in the loopless face.
- Liquid Glass surfaces over a lit field: a high-key white void with a faint azure glow in light, frosted graphite over a deep navy night in dark. The top bar is a floating capsule; the call action floats in a glass dock.
- Light and dark appearances. The console follows the system until the operator picks one with the sun/moon toggle (top bar, and top-right of sign-in), then remembers it. Switching grows the new appearance in a circle from the toggle.

## Colors

The palette is cool and quiet: navy-tinted neutrals, a single KPI blue accent, navy kept for the live call, and soft tints for meaning.

### Primary
- **KPI Blue** (`kpi-blue`): used only for the action and the current selection. That covers primary pill buttons, checked radio circles, the selected tile's border and icon well, plain text buttons, the label of a focused row, customer bubbles, the focus ring (at 40% alpha) and the text caret.
- **Pressed Blue** (`kpi-blue-press`): the hover/press state of primary buttons, and the text colour of tinted buttons.
- **Blue Tint** (`kpi-blue-tint`): the background of tinted secondary buttons, the hover background of plain buttons, and the info alert background.

### Secondary
- **Call Navy** (`kpi-navy`) and **Lifted Navy** (`kpi-navy-2`): the live-call header, painted as a radial gradient from Lifted Navy at the top-left corner to Call Navy by 60%. Navy also sets the wordmark and info-alert text. Every separator, shadow and backdrop is a navy alpha, so neutrals stay on the same hue.

### Tertiary
- **Sky** (`kpi-sky`): used only for the segment of the script-progress strip that is in progress. It never fills buttons or surfaces.

### Neutral
- **Grouped Grey** (`ground`): the page ground, sheet background and dock backdrop.
- **White** (`surface`): groups, tiles, panels, the call outcome card and the selected segment.
- **Whisper** (`surface-2`): row and table hover, and quoted customer text.
- **Fill** (`fill`): grey tracks for segmented controls and tabs, bot bubbles, idle icon wells, neutral pills and toolbar selects.
- **Hairline** (`separator`) and **Strong Hairline** (`separator-strong`): inset row separators and bar borders; control and check-circle strokes.
- **Ink** (`ink`), **Ink Secondary** (`ink-2`) and **Ink Tertiary** (`ink-3`): primary text; secondary text (descriptions, group headers, captions, table headers); placeholders, chevrons, speaker labels and unspoken bubble text. Ink Tertiary is only a small step lighter than Ink Secondary, so it stays readable when projected.

### Semantic
- **Good / Warn / Bad** (`good`/`good-bg`, `warn`/`warn-bg`, `bad`/`bad-bg`): always used as tinted pairs, with a deep text colour on a pale tint. They appear in status pills, alerts, outcome icon wells, field hints and the danger button. The live status dot in the call header uses a brighter green (#5fd38a) and a failed progress segment uses #ff8a8a. Both are tuned to sit on navy and appear nowhere else.

### Named Rules
**The One Job Rule.** Blue means "act here" or "this is chosen". If an element is neither an action nor a selection, it does not get blue.

**The Navy Means Live Rule.** The navy gradient is reserved for the call in progress. It never becomes a page header, card or button fill elsewhere.

**The Word Plus Tint Rule.** Status is always a word inside a tinted pill or alert. Colour never carries state on its own.

## Typography

**Interface Font:** Noto Sans Thai (with Noto Sans, -apple-system, Segoe UI, system-ui)
**Spoken Font:** Noto Sans Thai Looped (with Noto Sans Thai)

**Character:** Interface text uses the modern loopless Thai face, which feels close to iOS system type. Speech uses the traditional looped face, so whatever the bot said and the customer answered reads as human language, clearly separate from the controls around it.

All sizes are rem on the viewport-scaled root (`clamp(15px, 0.35vw + 12.5px, 19px)`): about 15px on phones, 17.5px at 1440px wide and 19px on large projectors. Never set type in px.

### Hierarchy
- **Display** (700, 2rem, 1.2, -0.01em): one large left-aligned page title per screen. The login title is a smaller 1.5rem version.
- **Headline** (600, 1.45rem, 1.25): the person's name in the call header.
- **Timer** (300, 2rem, 1, tabular): the call timer. It is light, large and set in tabular figures so it does not jitter.
- **Title** (600, 1.05–1.15rem): tile titles, outcome title, sheet title (1.1rem) and panel titles (1rem).
- **Body** (400, 1rem, 1.55): rows, inputs and buttons (500). Large buttons use 1.1rem at 600.
- **Spoken** (400, 0.95rem, 1.55): conversation bubbles, quoted customer verbatims (0.88rem) and the script textarea.
- **Label** (600, 0.85rem, ink-2): sentence-case group headers above a group, and in-panel subheads (0.82rem).
- **Caption** (400, 0.72–0.82rem, ink-2/ink-3): hints, notes, pill text (0.8rem, 500), progress labels and speaker labels.

### Named Rules
**The Looped Is Spoken Rule.** Use the looped face only for words that were spoken or typed in the conversation (bubbles, verbatim quotes, script text). Every label, button and heading uses the interface face.

**The Tabular Numbers Rule.** Any number that changes or appears in a column (timer, scores, phone numbers, counts) uses `font-variant-numeric: tabular-nums`.

## Layout

The layout is a single centred column with at most 76rem of content (44rem on narrow pages) and 1rem gutters. Pages run 1.75rem top padding and 6rem bottom padding, so the fixed dock on phones never covers content. Content is stacked as sections: a label header, then one group, with 1.75rem between sections. Rows are flex lines: a label column of 8.5rem, then the input, then trailing content. Campaign tiles use an auto-fit grid (min 14rem, gap 0.75rem). Live-call content is arranged as a call header over a two-column body (1.35fr conversation, 1fr captured results, gap 1rem).

Spacing follows a rem rhythm of 0.25, 0.5, 0.75, 1, 1.25 and 1.75rem. Gaps inside components fall between 0.35 and 0.9rem.

Responsive behaviour, in rem-scaled pixel breakpoints:
- **≤980px:** the call body collapses to one column.
- **≤760px:** the history table is replaced by a list of tappable rows.
- **≤720px:** progress labels hide except for the current step, and outcome actions wrap into a full-width row of equal buttons.
- **≤640px:** the top bar drops the product name and mode chip, and its tabs stretch to fill the width. The call dock and hang-up dock become fixed, blurred bottom bars that respect `safe-area-inset-bottom`. The transcript stops scrolling on its own and flows with the page. The side sheet goes full screen and slides up.
- **≤560px:** the call header wraps, with a smaller avatar and the timer row spanning the full width.
- **≤520px:** field rows stack the label above the input, and tiles become compact horizontal rows.

## Elevation & Depth

Depth comes from Liquid Glass (`apps/web/src/theme.css`). One material recipe is shared by groups, tiles, panels, the outcome card, the call header, the top-bar capsule, the docks and the sign-in card:

- **Fill:** translucent surface (`rgba(255,255,255,0.62)` light, `rgba(30,40,64,0.5)` dark).
- **Blur:** `blur(26px) saturate(185%)` on the backdrop.
- **Specular rim:** a 1px gradient ring, brightest along the top edge and faint down the sides (a masked `::after`).
- **Lift:** `0 1px 1px` plus `0 14px 34px` navy alpha in light; a deeper `0 18px 44px` near-black in dark.

Behind everything sits the **lit field**: fixed radial glows (azure, sky, a little lavender in light; KPI blue, sky and indigo in dark) blurred 40px and drifting very slowly (40s). Glass reads as glass only because there is a field to refract.

### Named Rules
**The Navy Shadow Rule.** Every shadow and scrim is tinted navy (near-black navy in dark). Never use neutral black.

**The Readable Glass Rule.** Glass never sits under text without enough opacity to hold contrast: the sheet is 90% opaque, bars 55–60%, groups 50–62%. `prefers-reduced-transparency` swaps every glass surface for a solid one.

**The Lifted Action Rule.** Primary buttons carry a top highlight and a soft blue glow; the selected segment thumb carries a small lift. Pills, inputs and bubbles stay flat.

## Shapes

The corners form a three-level family. Groups, tiles, panels, the call header and skeletons use 18px (`group`). Text controls and alerts use 12px (`control`). Anything that is a button, tab, pill or progress bar is fully round (`pill`). Inner pieces nest one step tighter: the segmented track and toolbar selects use 0.7rem, segments 0.55rem, tile icon wells 0.8rem and quotes 0.7rem. Avatars, check circles, outcome icon wells and status dots are perfect circles. Message bubbles use 1.1rem corners with a 0.35rem tail corner on the speaker's side (bottom-left for the bot, bottom-right for the customer). Row separators start 1rem in from the left edge and run to the right edge, as in iOS lists. Groups clip their contents (`overflow: hidden`), so rows inherit the corners.

## Components

### Buttons
Calm pills that press in.
- **Shape:** fully round (999px). Weight 500, label with an optional leading icon (gap 0.45rem).
- **Primary:** KPI Blue fill with white text. The large version (1.1rem, 600, 0.9rem × 1.5rem padding) is the one Call button at the end of the setup column, capped at 26rem wide.
- **Tinted:** Blue Tint fill with Pressed Blue text, for secondary actions (open detail, export, upload).
- **Plain:** text-only blue that gets a tint on hover, for inline actions.
- **Danger:** Bad tint fill with Bad text, for hang-up and delete. It is never a solid red fill.
- **States:** hover deepens the fill. Pressing scales to 0.98. Disabled is 45% opacity. Focus uses the global 3px blue ring at 40% alpha, offset 2px. Transitions run 150ms on `--ease`.

### Grouped List (signature container)
- **Corner / background:** 18px, white, Group shadow, contents clipped.
- **Rows:** at least 3.25rem tall, 0.6rem × 1rem padding, with an inset 1px hairline between rows. A field row has an 8.5rem label (500) followed by a borderless, transparent input. When the input has focus, the label turns KPI Blue. This is the system's only field focus cue besides the ring.
- **Choice rows:** a hidden native radio with a 1.4rem circle check. When checked, the circle fills KPI Blue with a white check. Rows get the Whisper background on hover.
- **Header / note:** a sentence-case label above the group (0.85rem, 600, ink-2, indented 0.25rem) and an optional caption note below it.

### Selectable Tiles
- White, 18px corners, Group shadow and a 1.5px transparent border, with an icon well (2.5rem, 0.8rem corners, Fill and ink-2) and a check circle in the top-right corner.
- **Selected:** blue border, blue icon well with a white icon, and a filled blue check. Hover deepens the shadow. Pressing scales to 0.99.

### Segmented Control and Tabs
- A Fill track with 0.2rem padding. Segments are transparent with ink-2 text at 0.9rem, 500. The selected item sits on a glass thumb (white 95% in light, white 16% in dark, top highlight plus a small lift) that **slides** to the new selection (500ms) instead of jumping. Top-bar tabs use the same pattern in a pill track, with a small green dot on the live-call tab. On phones a segmented control wider than the screen scrolls sideways.

### Inputs
- **In-group:** borderless rows (see Grouped List).
- **Stand-alone select/textarea:** white, 1px Strong Hairline border, 12px corners, 0.6rem × 0.8rem padding. Textareas showing script text use the spoken face.
- **Hints:** captions under the group, coloured good or bad when they confirm or reject input.

### Status Pills and Alerts
- **Pills:** 0.8rem, 500, fully round, a tint pair per meaning (good/warn/bad/neutral). The MOCK pill is warn-tinted, 0.72rem, 600, with 0.04em tracking.
- **Alerts:** 12px corners with a leading icon, coloured err (bad), warn, or info (Blue Tint with navy text).

### Call Header (signature)
- Radial navy gradient, white text, 18px corners and the Call shadow. A translucent white avatar circle holds the initials. Below it are the name (headline) and meta line (78% white), then the large light timer and a live status with a pulsing green dot (1.6s) that turns static white at 50% when idle. While the call is live, the hang-up button sits at the right end of the header row. On phones it becomes the fixed bottom dock.
- **Script progress strip:** one equal column per script step, each a 0.3rem rounded bar on 18% white. The bar fills white when done, Sky to 45% when current, and #ff8a8a when failed, animating `scaleX` over 400ms. Labels are 0.72rem at 62% white, brightening to 95% for done and current steps.

### Conversation Bubbles (signature)
- The transcript uses the spoken face. Bubbles are capped at 82% width, with 0.55rem × 0.85rem padding and 1.1rem corners plus a tail corner. Bot bubbles are Fill-grey, left-aligned. Customer bubbles are KPI Blue with white text, right-aligned. A speaker label (0.72rem, ink-3, interface face) sits above each turn, with a warn-coloured mark when the turn was interrupted.
- **Unspoken text:** any part of a bot turn that was cut off before it was spoken is shown in ink-3 with a line-through. It is never presented as delivered.
- A three-dot typing indicator in a bot-shaped bubble shows the bot is composing. Each bubble rises in over 250ms. On wide screens the transcript scrolls inside a mask that fades out at the top.

### Docks, Outcome and Sheet
- **Call dock:** a floating glass capsule (max 28rem, 1.75rem corners) that sticks 1rem above the bottom of the column, holding the one primary action and its caption; content scrolls beneath it, blurred. On phones it floats 0.75rem in from the edges. The **hang-up dock** follows the same phone behaviour, with a full-width danger button.
- **Outcome card:** white, 18px, a circular tint icon well, a title and subtitle, and trailing actions. It rises in over 350ms.
- **Side sheet:** a ground-coloured panel up to 40rem wide that slides in from the right (280ms) over a navy scrim fading in at 200ms. It has a sticky blurred header. The call facts open the sheet as a two-column info grid (caption label over value, inset hairlines). On phones it is full screen and slides up.

### Icons
- A single authored SVG family on a 24-unit grid: stroke `currentColor`, 1.75 width, round caps and joins, 20px by default, `aria-hidden`. Icons take the colour of their context.

### Motion
- Critically damped, never bouncy: `--ease-glass` `cubic-bezier(0.32, 0.72, 0, 1)` for surfaces and screens, `--ease-snap` `cubic-bezier(0.16, 1, 0.3, 1)` for thumbs, presses and bubbles.
- **Screen changes** (tabs, starting a call, a new call) cross-fade with the View Transitions API: the old screen fades and settles back in 200ms, the new one rises 0.6rem in 420ms; the top bar stays put.
- **Theme switch:** the new appearance is revealed in a circle growing from the toggle (600ms); the sun and moon trade places with a quarter turn.
- **Sliding thumbs** on tabs and segmented controls (500ms); **presses** scale buttons to 0.96 and tiles to 0.98; **bubbles** grow in from their speaker's corner (420ms); the **sheet** glides in from the right (500ms).
- `prefers-reduced-motion` turns off transitions, the field drift and every animation.

## Do's and Don'ts

### Do:
- **Do** put every set of inputs or options in a white 18px group on the `#f5f6f8` ground, with inset hairline separators and a sentence-case label header above it.
- **Do** keep one primary pill action per step. On phones, dock it at the bottom in a blurred bar.
- **Do** size everything in rem so the viewport-scaled root carries it to projectors.
- **Do** use tabular numerals for timers, scores, counts and phone numbers.
- **Do** show interrupted bot speech as struck-through ink-3 text, and label all mock data with the MOCK pill.
- **Do** tint every shadow, separator and scrim with navy alpha.
- **Do** honour `prefers-reduced-motion` for any new animation.

### Don't:
- **Don't** use KPI blue for decoration, headings or non-interactive emphasis. It is reserved for action and selection.
- **Don't** use the navy gradient anywhere except the live-call header, and don't put gradients on text.
- **Don't** fill buttons or surfaces with Sky. It marks only the current script step.
- **Don't** use emoji or icon fonts. Use the 1.75-stroke SVG family.
- **Don't** set interface labels in the looped face, or conversation text in the loopless face.
- **Don't** put shadows on buttons, pills, inputs or bubbles.
- **Don't** convey call state by colour alone.
- **Don't** recolour, stretch or redraw the KPI logo. Use the supplied file as is, on a white plate when the ground is navy.
- **Don't** add dashboard charts or analytics panels, or put form, live call and history on one screen. Show one task per screen.
