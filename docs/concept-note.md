# Kobo in a box: concept note

**Offline data collection, analysis and AI for humanitarian teams working without reliable internet**

KoboToolbox · Draft for partners and donors · October 2026

---

## Summary

Humanitarian teams often work where internet access is missing, unreliable, expensive,
monitored or deliberately shut down: after a hurricane, in an active conflict, in a
remote camp, or in a district where mobile data costs more than a day's wages. Most
digital data tools assume a connection. When there isn't one, teams fall back on paper,
delays, or risky workarounds that put sensitive data on personal phones and consumer
cloud services.

**Kobo in a box** is a self-contained field kit: a small computer, a Wi-Fi access point
and a portable power supply that together run the full KoboToolbox platform with **no
internet at all**. Enumerators' phones and tablets connect to the box's own Wi-Fi to
download forms, submit data and install the apps they need. Supervisors design forms,
monitor submissions, clean data and export results on site.

Kits work alone or together. A single kit can run a whole project and never connect to
anything. Several kits at different sites can feed one **hub kit** at a base, which
combines their data for analysis and reporting, still with no internet. And whenever
a connection is available, a kit or hub can sync its data to a KoboToolbox server in the
cloud. Each organisation decides, project by project, how far its data travels.

The new generation of the kit adds four things:

1. **Local AI processing inside KoboToolbox.** Transcription of recorded interviews,
   translation, and qualitative analysis run on the box itself using open AI models.
   Recordings and responses never leave the device, and there are no per-use fees.
2. **AI assistants for field analysis.** Field staff can ask questions about their data
   in plain language ("summarise this week's submissions by district", "find likely
   duplicates", "draft a one-page update") and get answers on the spot, without an
   analyst or a connection. The assistant can also build **live dashboards**: maps,
   charts and short data stories that update as new submissions arrive, and that anyone
   on the box's Wi-Fi can open in a browser.
3. **A local knowledge base.** The assistant draws on the KoboToolbox, KoboCollect,
   XLSForm and ODK guides, and on whatever documents an organisation adds (procedures,
   protocols, sector guidance, earlier assessments), so it can answer "how do I…?" and
   "what does our protocol say…?" questions, pointing to the page it used.
4. **An offline library.** Any device on the box's Wi-Fi can open a local web page with
   the apps (KoboCollect, QGIS, QField, LibreOffice) and guides (the KoboToolbox user
   guide in English, Spanish and French; QGIS manuals) that teams need, so phones and
   laptops can be set up from scratch in the field.

The basic kit has already been used in the field, most recently in Kobo's response to
Hurricane Melissa in Jamaica. The AI processing, the AI assistant and the library are
working in a simulated offline test environment, as described below; dashboards and the
knowledge base are built for KoboToolbox's online services and are being adapted to run
on the box. The next step is a **field pilot with one
partner organisation**, followed by a packaged kit that can be installed on new hardware
from a single USB stick.

---

## 1. The problem

### Connectivity is the exception, not the rule, where humanitarian need is highest

- **Sudden-onset disasters** destroy mobile masts and power lines exactly when rapid
  needs assessments are most urgent. Satellite links are slow, costly and shared by
  everyone in the response.
- **Conflict and insecurity** bring deliberate internet shutdowns, surveillance of
  network traffic, and risk to staff seen using connected devices.
- **Remote and displaced populations** live where coverage is patchy or absent, and
  mobile data is a significant cost for organisations running large teams.
- **Large teams on weak links** create bottlenecks: dozens of enumerators trying to
  submit data, photos and audio over one poor connection at the end of each day.

### The workarounds create their own risks

Without a reliable connection, teams typically:

- go back to paper, adding weeks of data entry, transcription errors and lost forms;
- hold data on individual phones for days or weeks, where it is easily lost, stolen
  or seen by others;
- move files with personal messaging apps, USB sticks and consumer cloud accounts,
  outside any data protection framework;
- delay analysis until staff return to an office, so findings arrive too late to change
  the response.

### AI tools make the gap wider

Transcription, translation and AI-assisted analysis can save humanitarian teams
enormous amounts of time, especially for qualitative interviews in local languages.
But today these tools are almost all cloud services. Using them means a fast
connection, recurring fees, and sending recordings of sensitive interviews to
third-party providers, often in other jurisdictions. For many protection, health and
conflict-affected contexts, that last point alone rules them out.

---

## 2. The solution

### What is in the kit

| Component | What it does |
|---|---|
| **Compact computer** (mini PC or laptop) | Runs KoboToolbox, the AI models and the library. Encrypted disk that unlocks automatically on the right hardware, so field staff don't need to manage passwords for it |
| **Wi-Fi access point** (USB Wi-Fi adapter or travel router) | Creates a local network that phones, tablets and laptops join. No SIM card or internet needed |
| **Portable power station + solar panel** | Runs the kit for a working day and recharges from solar, a vehicle or mains |
| **Rugged case** | Protection from dust, heat and transport |
| **Optional: preconfigured Android devices** | Ready-to-use phones or tablets for enumerators |

### What people can do with it

**Enumerators** connect to the box's Wi-Fi, open `kobo.local` in a browser, install
KoboCollect directly from the box, and collect data offline as they do today. When
they come back in range of the box's Wi-Fi (at the end of the day, or at a base
location), submissions upload in seconds, including photos and audio recordings.

**Supervisors and managers** use the full KoboToolbox web interface from any laptop on
the box's Wi-Fi: build and deploy forms, monitor incoming data, validate and clean
submissions, view maps and reports, and export to Excel, CSV or GIS formats.

**Analysts and programme staff** use:
- **Automatic transcription** of recorded interviews (e.g. from a KoboCollect audio
  question), so hours of audio become searchable text overnight;
- **Automatic translation** of transcripts and open-text answers into a working
  language;
- **AI-assisted qualitative analysis**, which suggests answers to analysis questions
  ("Which water sources does the respondent mention?") for staff to review and accept;
- **An AI assistant** that can query, summarise and check the project's data, and draft
  reports, in plain language;
- **Live dashboards** built by the assistant from a request such as "a dashboard of this
  assessment by district, with a map of reported damage". Staff refine them by asking,
  and share them with colleagues on the box's Wi-Fi, open or behind a password. They
  update as enumerators sync, and can combine several projects.

**Everyone** has an offline library of installers and guides: the KoboToolbox user guide,
QGIS and QField for mapping, LibreOffice for editing forms and opening exports, and
more as each deployment needs.

**Anyone who is stuck** can ask the assistant. With no internet there is no help centre,
forum or helpdesk to turn to, so the knowledge base stands in for them: "how do I make
this question appear only for women over 18?", "why does KoboCollect say the form has an
error?", "what does our referral protocol say about urgent cases?". Answers cite the page
they came from, which opens on the box.

### Dashboards and the knowledge base

Both components already exist as KoboToolbox online services: Kobo's dashboard service,
which its assistant tools drive, and the support chatbot on Kobo's help centre, which
answers from the user guides. On the kit they run with the same local AI model as the
assistant:

- **Dashboards** read data from the kit's own KoboToolbox. Map backgrounds and
  administrative boundaries for the deployment's regions are loaded before the mission
  (maps still show points and shaded areas without a background). Desk research, which
  online uses the web, uses the documents in the knowledge base instead.
- **The knowledge base** holds the official guides in English, Spanish and French and
  works across languages: a question asked in another language still finds the right
  page. Each kit's focal point can add documents before or during a deployment; they are
  indexed on the box. It is for reference material, not personal data: survey responses
  stay in KoboToolbox, where the assistant reaches them only with the user's own
  permissions.

### Three ways to run it: alone, as a network, or connected

```
  Site A kit ──┐
  Site B kit ──┼── (at base, over a cable or local Wi-Fi) ──▶  Hub kit  ──(when online)──▶  KoboToolbox
  Site C kit ──┘                                            analysis,                     cloud server
                                                            reports                       (optional)
```

1. **Standalone.** One kit runs a project from start to finish: data collection,
   cleaning, AI processing, analysis and reports. Nothing ever leaves the device. This
   suits short assessments and the most sensitive data.
2. **Networked (federated).** Several kits run at different sites with the same forms.
   When a kit comes back to base (or is connected by cable or a local link), its new
   submissions are copied to a hub kit. The hub holds the combined dataset from all sites,
   and its AI assistant analyses and reports across them, still fully offline. Field kits
   can be the cheaper budget tier; only the hub needs the recommended hardware.
3. **Connected.** When any connection is available (even briefly, or over satellite), a
   kit or the hub syncs to a cloud KoboToolbox server: KoboToolbox's Global or EU servers,
   or the organisation's own private server. The offline deployment then joins the
   organisation's normal data management.

Organisations can mix these: for example, keep a protection project standalone while a
needs assessment syncs to the cloud every time the hub gets a connection.

**How syncing works.** Syncing uses **kobo-transfer**, Kobo's open-source tool for copying
projects and submissions between KoboToolbox servers. It already handles what field
syncing needs:
- **Safe to repeat.** Every submission keeps its original unique ID, so syncing again
  only sends new submissions. Nothing is duplicated, even when data from many kits ends
  up in one project.
- **Complete.** Photos, audio and other attachments, validation statuses, and the
  results of analysis (transcripts, translations, qualitative coding) travel with the
  data, so AI processing done offline is not lost.
- **Robust on poor links.** Large projects are sent in batches, and failed submissions
  can be retried on their own.
- **One direction.** Data flows from field kits to the hub to the cloud. Forms are
  deployed identically on every kit before the mission, and each kit marks its
  submissions with its own site identifier, so the combined data shows where each
  record came from.

### Design principles

- **Nothing depends on the internet.** Every service, model, font and help page is on
  the box. We test this by cutting all outbound traffic and checking that everything
  still works.
- **Data stays where it is collected.** Recordings, responses and AI outputs are processed
  and stored on the device. No third-party AI provider sees them.
- **AI suggests, people decide.** AI outputs are clearly marked suggestions that staff
  review, edit or reject. Risky actions by AI assistants (deleting data, changing forms)
  are blocked or need explicit confirmation.
- **Open and replaceable.** Built entirely from open-source software and openly licensed
  AI models that permit commercial and humanitarian use. Standard, widely available
  x86 hardware (the same kind of chips as most laptops) that can be bought, repaired or
  replaced locally.
- **Preconfigured, not configured in the field.** Kits are prepared before deployment.
  In the field, someone only needs to switch it on, connect to the Wi-Fi and open a web
  page.

---

## 3. What has been done so far

### Field use of the basic kit

- **Prototype (v0.1).** A second-hand ThinkPad laptop (8 GB of memory), a donated
  Wi-Fi router, a 155 Wh power station and a hard-shell case. It ran KoboToolbox fully
  offline over the local Wi-Fi, with custom branding, scripts to create user accounts,
  and a tested sync of the collected data to a cloud KoboToolbox server afterwards
  with kobo-transfer.
- **Hurricane Melissa response, Jamaica.** As part of Kobo's response, the offline setup
  was used in the field: KoboToolbox running on a laptop, a USB Wi-Fi adapter in place of
  a separate router, and staff downloading the KoboCollect app straight from the laptop
  over the local network. Lessons from the deployment shaped this plan: serving files
  locally is essential, the setup must be simple enough to need no networking
  expertise, and the kit should ship ready to run, including on a preloaded USB stick.

### Testing of the AI and library components (October 2026)

We built a test environment in the cloud that simulates the field kit, including a
switch that cuts all internet access. We tested on two kinds of machine: an ordinary
8-core computer with no graphics card (the slowest hardware tier we would consider), and
a data-centre graphics card standing in for the recommended tier while it is out of stock
(it shows how much memory each part needs, but runs faster than field hardware will).

| What was tested | Result |
|---|---|
| KoboToolbox running fully offline with local AI | Works. All AI features and the full KoboToolbox workflow (create form, deploy, submit, analyse) pass with internet blocked |
| AI features inside KoboToolbox | Qualitative analysis, translation and transcription all work through KoboToolbox's own interface on the local models, with internet blocked. Long jobs run in the background, so slow hardware doesn't time out. The changes pass KoboToolbox's own test suite |
| Transcription accuracy (Spanish) | About **2% word error rate** on a standard public speech benchmark. This is clean read speech, so a best case: real interviews recorded on phones will be harder and need testing per language |
| Translation | Correct translations, about 2 seconds per answer |
| AI-assisted qualitative analysis | 3 out of 3 test questions answered correctly in KoboToolbox's own format, 6–17 seconds each |
| Transcription speed | Roughly twice the length of the recording on this slow hardware: fine for overnight processing, too slow for instant results. Much faster on the recommended hardware |
| AI assistant (agent) | Too slow without a graphics card. With one, on 30 realistic field requests about a test survey ("how many households per district?", "find the duplicates", "put the duplicates on hold"): the larger model (gpt-oss-120b) got **24 of 30** right, including every change to data; the smaller one (Gemma 4 26B) got **22 of 30**, reliable for questions but not for changes |
| AI assistant safety | Both models refused every request to delete data (deleting is blocked) and never touched another server, also with internet blocked. Changes are set to need the user's confirmation; checking that this applies to every KoboToolbox action is part of the next round |
| Memory needed per tier | Transcription plus translation and analysis fit a laptop graphics card with 8 GB. The larger assistant model needs about 63 GB, so it runs only on the recommended 128 GB tier |
| Offline library | 13 installers and documents (about 5 GB), each checked against a published or recorded fingerprint; guides load with no internet; large uploads (a 40 MB audio interview) and downloads work through the box |

Performance on the recommended field hardware still needs to be confirmed on a real
device: this is the first purchase in the next phase. The assistant re-reads its
instructions, about 15,000 words, at every step, and a request takes several steps, so how
fast the hardware reads long inputs will matter more than how fast it writes answers.

---

## 4. Practical implications in complex and challenging environments

This section sets out what the kit changes in practice, and what it does not, for the
contexts where it matters most.

### 4.1 Speed and continuity of operations

- **Data collection can start on day one** of a response, before connectivity is
  restored, without waiting for satellite links or mobile networks.
- **Daily data flow doesn't depend on the network.** Enumerators sync to the box when
  they come back to base, so supervisors see the day's data the same evening and can
  fix problems (a misunderstood question, a missed area) before the next day.
- **Analysis happens where decisions are made.** Field coordinators get summaries,
  maps and translated interview excerpts on site, rather than weeks later from a
  headquarters analyst.
- **Qualitative data becomes usable at scale.** Interviews recorded in local languages
  can be transcribed and translated overnight. Today, many organisations limit
  qualitative work because manual transcription and translation cost too much and take
  too long.
- **Many sites, one picture.** With a hub kit, coordinators see combined data from every
  site as teams rotate back to base, and can compare districts, spot gaps and adjust
  plans across the whole operation without a connection.
- **Setup time.** Phones and laptops can be set up entirely from the box: apps,
  KoboCollect project settings and guides, with no app store or internet needed.

### 4.2 Data protection and the safety of people

Kobo in a box gives organisations more control over sensitive data, and it also moves
risk to a single physical device. Both sides need managing.

**What improves:**
- **No third-party processing.** Interview recordings, transcripts and AI analysis never
  leave the device. This matters most for protection monitoring, gender-based violence,
  health, and interviews in conflict settings, where sending recordings to a commercial
  cloud AI service is unacceptable.
- **Less data on personal devices.** Submissions move off enumerators' phones to an
  encrypted, organisation-controlled device every day, instead of staying on phones for
  weeks.
- **No exposure on monitored networks.** Data doesn't cross local or national networks
  that may be monitored, and the kit keeps working through internet shutdowns.
- **Control over where data goes.** Syncing is a deliberate choice for each project,
  not a default: some projects can stay on the kits for good, others go only as far as
  the hub, others on to a named cloud server. Syncing uses a dedicated account with
  access only to the projects being sent.
- **Data sovereignty.** Data can stay in-country, under the organisation's and
  community's control, which helps where national rules restrict sending personal data
  abroad or to cloud providers.

**New risks, and how they are handled:**

| Risk | Mitigation |
|---|---|
| Theft or loss of the box | Full-disk encryption; strong Wi-Fi password; no services reachable beyond the local Wi-Fi; regular encrypted backups to a second device kept separately |
| Seizure, or staff forced to unlock it | Encryption protects data at rest, not against coercion. Collect only the data needed; delete or sync off-site on a regular schedule; agree in advance what staff should do if the box is demanded; where the risk is high, treat the kit as a staging point rather than long-term storage |
| An untrusted device joins the Wi-Fi | Strong, regularly changed Wi-Fi password; every KoboToolbox user needs their own account and permissions; the AI assistant works with the logged-in user's own permissions only |
| A single point of failure | Backups to a second device; sync to the cloud when possible; the hardware is standard and replaceable, and the software can be reinstalled from USB |
| AI assistants keep conversation histories containing personal data | Stored only on the encrypted device; a retention and deletion policy for each deployment |
| A dashboard shows more than intended to people on the Wi-Fi | New dashboards start unpublished; sensitive ones use a password; dashboards show summaries, and the owner chooses what goes on them |
| Documents added to the knowledge base contain personal data, or text written to mislead the assistant | The knowledge base is for reference material only; the assistant treats document text as information, not instructions, and still can't delete data or make changes without confirmation |

**Responsible data practice still applies in full.** The kit makes it easier, not
optional: informed consent (including for audio recording), data minimisation, access
control, retention limits, and a data-sharing plan for when data moves to the cloud.

### 4.3 Responsible use of AI

- **Human review is built in.** In KoboToolbox, automatic transcriptions, translations
  and qualitative analysis are suggestions that staff check and correct before they're
  used. The AI assistant can't delete data, and must ask before making any change. In
  testing, both assistant models refused every request to delete data.
- **The assistant makes mistakes, so its answers need checking.** In our tests it
  sometimes misread which question held the information (counting interviews by the
  staff account that uploaded them rather than by the enumerator question), and the
  smaller model sometimes stopped without answering or repeated an action many times.
  We will measure this on each deployment's own forms, give the assistant guidance on
  the form, and recommend the larger model wherever the assistant is allowed to change
  data.
- **Language coverage varies.** The AI models work well in major languages (we have
  measured Spanish, and have sample checks for French, Portuguese and Swahili) and less well,
  or not at all, in many minority languages. **Each deployment's languages must be
  tested before relying on AI output,** using about 50 real recordings per language.
  Where quality is not good enough, the kit still works fully without AI, and models
  for specific languages can be added or adapted.
- **Errors are expected and measured.** We publish measured error rates per language
  and per hardware tier, so teams know how much checking is needed.
- **Answers show their sources.** The assistant cites the guide or document behind each
  answer, and says so when the knowledge base doesn't cover a question rather than
  guessing.
- **Transparency with respondents.** Consent wording should explain that recordings may
  be transcribed and translated automatically, on a device the organisation controls.
- **No hidden costs or lock-in.** The models run locally under open licences that allow
  humanitarian and commercial use. We deliberately exclude models whose licences
  forbid commercial use.

### 4.4 Power, heat and the physical environment

- **Power.** The recommended computer draws roughly 50–120 W under load, and its power
  limit can be lowered to 45–65 W on battery. A 500 Wh or larger power station with a
  100–200 W solar panel is the starting point. Exact sizing will come from measurements
  in the pilot.
- **Power-aware operation.** Heavy AI jobs (bulk transcription) run when the kit is on
  mains or solar power, usually overnight. Interactive work and data collection come
  first.
- **Heat and dust.** Cases with airflow and dust filters; the pilot will log
  temperatures and any slowdown from overheating.
- **Battery as backup.** A laptop form factor has its own battery, which works as a
  built-in uninterruptible power supply. A mini PC is cheaper and easier to swap. The
  pilot will inform the choice.

### 4.5 Logistics, procurement and maintenance

- **Standard hardware.** The kit uses widely sold x86 mini PCs or laptops, not
  specialist equipment. They can be bought regionally, repaired by local technicians,
  and replaced without re-engineering.
- **Customs and import.** Kits contain encrypted computers and radio equipment (Wi-Fi).
  Some countries restrict importing encryption technology or require registering
  wireless equipment. Check this for each deployment country, and carry documentation.
- **Installation from USB.** New kits are installed from a single USB stick holding the
  operating system, KoboToolbox, the AI models and the library. Each kit gets its own
  passwords and keys on first start-up, printed on a label card. Updating a fleet of kits
  means copying a new version of the content to the USB stick, not re-engineering.
- **Updates.** Kits can't update themselves in the field. Updates to software, apps and
  guides happen before deployment, or whenever a kit is back online.

### 4.6 People and skills

- **Designed for non-technical field staff.** Day-to-day use needs a browser and the
  Wi-Fi password. The landing page at `kobo.local` explains each step.
- **One trained focal point per deployment** handles power, backups, user accounts and
  first-line troubleshooting. A short guide and checklist come with the kit.
- **Local language interfaces.** KoboToolbox, KoboCollect and the user guides are
  available in several languages; the library can include guides in the languages of
  each deployment.
- **Remote support is limited by design.** With no internet there is no remote
  helpdesk, so the kit must be robust and self-explanatory, and the focal point needs
  good preparation. The pilot will show what training is enough.

### 4.7 Cost and sustainability

- **One-off hardware costs, no running costs for AI.** Cloud AI services charge per minute
  of audio or per request, which quickly adds up for large qualitative datasets. On the
  box, transcribing and analysing more data costs nothing extra.
- **Indicative hardware cost** (October 2026 prices, to be confirmed):
  - Recommended kit computer (128 GB unified memory, runs all AI features including the
    assistant): about **$2,000–2,800**.
  - Budget computer (64–96 GB, runs AI processing in KoboToolbox; slower for the
    assistant): about **$800–1,200**.
  - Plus power station, solar panel, Wi-Fi equipment and case. These will be costed from
    pilot power measurements.
- **Field kits and hubs can differ.** In a networked deployment, only the hub needs the
  recommended hardware for AI assistants. Field kits can be the budget tier, which still
  runs KoboToolbox and overnight transcription and translation.
- **Kits can be reused** across deployments and organisations, and refurbished between
  uses.
- **No proprietary licences.** Every software component is open source. Our changes to
  KoboToolbox are designed to be merged into the main KoboToolbox product, so all
  self-hosted KoboToolbox users benefit, and so we don't maintain a separate version.

### 4.8 What the kit does not do

Being clear about limits is part of using the kit responsibly:

- It does **not replace connectivity for coordination**: emails, cluster reporting and
  calls with headquarters still need a connection, even an occasional one.
- Each kit serves **one site at a time**, over its own Wi-Fi. Combining sites needs a
  kit to come back to base or a physical link (cable, local radio link) to the hub;
  sites with no link at all are combined when the kit is carried back.
- **Syncing is one-way, for new data.** Edits made on a field kit after its data has
  already reached the hub or the cloud may not be carried across automatically. This is
  being tested; the likely practice is to clean data in one place (the hub) or sync
  once cleaning is finished.
- **KoboCollect runs on Android.** Staff with iPhones or laptops can still collect data
  through web forms in the browser.
- **The knowledge base and maps are only as complete and current as what was loaded**
  before deployment. Desk research is limited to documents brought on the kit, and maps
  cover the regions prepared for the mission.
- **AI quality in many languages is not yet proven**, and real field recordings (noise,
  overlapping speakers, dialects) will perform worse than benchmarks.
- **How many people one box can serve at once** (enumerators syncing, staff using the AI
  assistant) is still to be measured. It is a key question for the pilot.

---

## 5. Illustrative scenarios

These scenarios show how the kit could be used. They are illustrations, not results.

**Rapid needs assessment after a cyclone.** Mobile networks are down across a coastal
district. A response team arrives with two kits. Within hours, 30 enumerators have
KoboCollect installed from the kits and the assessment form loaded. Each evening, data
from the day's villages is synced at the base, and the coordinator reviews a map of
reported damage and needs to plan the next day's distributions, days before the
network is back.

**Protection monitoring in a displacement camp.** Monitors record interviews in the
local language with consent. Overnight, the kit transcribes and translates them. In the
morning, a protection officer reviews the translations alongside AI-suggested themes
(safety concerns, access to services), corrects them, and flags urgent cases. No
recording leaves the camp, and nothing passes through a third-party service.

**Multi-district assessment with a hub.** Four teams cover four districts, each with a
budget kit, and rotate back to a field base every few days. At the base, each kit is
plugged into the hub, and its new submissions, photos and transcribed interviews are
copied across in minutes. The hub's AI assistant produces a weekly cross-district
summary for the coordination meeting. Once a week, when the base gets a satellite
window, the hub syncs everything to the organisation's KoboToolbox server, so
headquarters sees the same data.

**Remote health facility survey.** A ministry and NGO team visits clinics across a
mountainous region over three weeks with no connectivity. The kit travels with the
team in a vehicle, powered by the vehicle and a solar panel. At the end of each day, the
supervisor asks the AI assistant for a check on missing data and likely duplicates, and
gets a list of follow-ups for the next visit. At the end of the mission, the data is
synced to the ministry's server.

**A new supervisor, no help desk.** A supervisor who joined the team last week needs to
add a question to the form that only appears for clinics with a maternity ward, and
then wants to know what the ministry's facility standards say about cold-chain
equipment. The supervisor asks the assistant on the kit. It explains the skip logic step by step,
citing the KoboToolbox guide, and quotes the relevant section of the ministry's
standards, which the team loaded onto the kit before leaving. That evening, the supervisor asks for
a dashboard comparing clinics against those standards and shares it with the team
leader on the kit's Wi-Fi.

---

## 6. Hardware approach

AI assistants need to process long instructions quickly, and the kit must hold
KoboToolbox and several AI models in memory at once. That rules out the cheapest
small computers (such as the Raspberry Pi), and KoboToolbox's software currently
requires standard x86 processors.

| Tier | Example | Supports | Approx. cost |
|---|---|---|---|
| **Recommended** | Mini PC or laptop with an AMD Ryzen AI Max+ 395 and 128 GB of unified memory | Everything: KoboToolbox, transcription, translation, qualitative analysis, and a capable AI assistant, using the same AI model KoboToolbox's cloud service uses for qualitative analysis | $2,000–2,800 |
| **Budget** | Ryzen mini PC with 64–96 GB of memory | KoboToolbox and its AI processing; a smaller assistant model, good for questions about the data but not trusted to change it | $800–1,200 |
| **KoboToolbox only** | Low-power mini PC with 16 GB of memory | Offline data collection and management, no AI | ~$200 |

A single development unit of the recommended tier is the first hardware purchase, to
confirm speed, power draw and heat before buying pilot kits.

---

## 7. Roadmap

| Phase | What | Status |
|---|---|---|
| **Foundations** | Offline KoboToolbox; cloud test environment with internet cut-off; AI models chosen and benchmarked | ✅ Done |
| **Offline library** | Local landing page, app installers and guides; checked to work with no internet | ✅ Working in testing |
| **AI processing in KoboToolbox** | Qualitative analysis, translation and transcription on local AI: working end to end and offline in testing. Next: languages for the pilot, and proposing the changes to the main KoboToolbox product | ✅ Working in testing |
| **AI assistant** | Assistant connected to KoboToolbox data, with safety limits on what it can change: working offline in testing, with a 30-task test set comparing models. Next: sign-in for several users, guidance about each form, shorter instructions for speed | ✅ Working in testing; 1–2 weeks more |
| **Dashboards** | Kobo's dashboard service running on the kit, built by the assistant; offline maps and boundaries for the deployment's regions | About 2 weeks, after the assistant connection |
| **Knowledge base** | Guides indexed on the box and searchable by the assistant, across languages; the deployment's own documents added before or during a mission; tested with the support chatbot's question set | 2–3 weeks; can start now |
| **Hardware** | Buy and test one recommended unit; measure speed, power and heat, re-running the same AI and assistant tests | Next |
| **Multi-site sync** | Kit-to-hub and hub-to-cloud syncing with kobo-transfer, automated and shown on the kit's status page; identical forms on every kit | Sync to a cloud server tested on the prototype; hub workflow to build and test |
| **Packaging** | One-USB installation; per-kit passwords and keys; health check page; quick-start guide | 2–4 weeks |
| **Field pilot** | One partner organisation, 3–6 languages, real conditions | After the above |
| **Scale-up** | Kits available to partners; changes merged into the main KoboToolbox product | After the pilot |

### The pilot

- **Partner:** one organisation running data collection in a low-connectivity setting.
  Candidate partners have been identified, including FAO in Tanzania and SGDD in
  Turkey.
- **Languages:** 3–6 languages chosen with the partner. For each, 5–10 practice
  interviews recorded on field phones through KoboCollect let us measure transcription
  and translation quality before the pilot starts.
- **What we will measure:** setup time; uptime; how long syncing takes (kit to hub, and
  over the available connection to the cloud); power use and battery life; temperatures;
  how many enumerators and staff one box supports; transcription and translation
  accuracy per language; time saved compared with manual transcription and translation;
  field staff experience; and any data protection incidents.
- **Outputs:** a pilot report, a tested deployment guide, a costed kit specification,
  and the software changes contributed to KoboToolbox.

---

## 8. How partners and donors can help

- **Fund kits and the pilot:** a development unit, pilot kits (computer, power, Wi-Fi,
  case, optional Android devices), and field costs for the pilot.
- **Fund development:** completing local transcription and translation in KoboToolbox,
  the AI assistant, dashboards and the knowledge base on the kit, and the one-USB
  installer.
- **Share reference material:** procedures, protocols and sector guidance (in the
  languages your teams use) that should travel with a kit's knowledge base.
- **Help with languages:** recordings and reference transcripts in the languages your
  operations use, so we can measure and improve AI quality for them.
- **Host a pilot:** an operation where offline data collection, qualitative interviews or
  sensitive data make this approach worth testing.
- **Share expertise:** data protection, field logistics, power systems, and
  localisation.

---

## 9. Why KoboToolbox

KoboToolbox is free and open-source software built for humanitarian and development
work, and is already used by humanitarian organisations around the world. Field teams
already know its forms, apps and workflows, so the kit adds offline capability and
local AI to a tool they already use, rather than introducing a new system. Building
these capabilities into KoboToolbox itself, and contributing them to the main product,
means they reach every organisation that runs its own KoboToolbox server, not only
those using a kit.

---

## Annex A. How it works (technical overview)

```
   Phones, tablets and laptops on the kit's Wi-Fi
   (KoboCollect app, web browser: kobo.local)
                 │
         ┌───────┴────────────────────────────────────────────┐
         │  Kit computer                                      │
         │                                                    │
         │  Web front door ── kobo.local: apps and guides     │
         │       │                                            │
         │       └── KoboToolbox (forms, data, web forms,     │
         │            exports, users and permissions)         │
         │                 │                                  │
         │                 ▼                                  │
         │  Local AI models                                   │
         │   · transcription (Whisper)                        │
         │   · translation and analysis (Gemma 4, gpt-oss)    │
         │                 ▲                                  │
         │  AI assistant (OpenCode) ── KoboToolbox data tools │
         │   with an analysis workspace (spreadsheets,        │
         │   charts, reports)                                 │
         │       ├── Dashboards ── kobo.local, on the Wi-Fi   │
         │       │    (offline maps and boundaries)           │
         │       └── Knowledge base: guides + local documents │
         │            (search across languages, cited pages)  │
         │                                                    │
         │  Encrypted disk · no internet required             │
         └────────────────────────────────────────────────────┘
                 │
         Optional: sync to a hub kit at base, and/or
         to a cloud KoboToolbox server when online
```

- **KoboToolbox:** the standard open-source release, installed with KoboToolbox's own
  installer and configured for offline local use.
- **AI models:** Whisper (MIT licence) for transcription; Gemma 4 (Apache 2.0) for
  translation and analysis on all tiers; gpt-oss-120b (Apache 2.0) on the recommended
  tier, the same model KoboToolbox's cloud service uses for qualitative analysis, so
  prompts and results are consistent online and offline. All run with the open-source
  llama.cpp and whisper.cpp engines.
- **AI assistant:** OpenCode (open source), connected to KoboToolbox through Kobo's MCP
  server (a standard way for AI assistants to use tools) with the logged-in user's
  permissions. Deleting data is blocked, and changes need confirmation. It uses its own
  copy of the AI model: gpt-oss-120b on the recommended tier, Gemma 4 26B on smaller
  ones, and is given only the KoboToolbox tools its job needs, which keeps its
  instructions shorter.
- **Dashboards:** Kobo's dashboard service (kobo-dash), driven by the MCP server's
  dashboard tools and reading data from the kit's KoboToolbox through a view-only
  account. Map backgrounds come from OpenStreetMap data prepared for the deployment's
  regions; administrative boundaries from geoBoundaries.
- **Knowledge base:** the guides and local documents split into sections and indexed
  with an open multilingual search model (bge-m3, MIT licence) in PostgreSQL, using both
  meaning and exact-word search. The assistant searches it through its own MCP server.
  Built on the chunking, ranking and test questions of Kobo's help-centre chatbot.
- **Sync:** kobo-transfer (open source, by Kobo), preinstalled on every kit. It copies new
  submissions, attachments, validation statuses and analysis results between KoboToolbox
  servers, one project at a time, keeping each submission's unique ID so repeat runs
  don't create duplicates.
- **Offline library:** a list of each app and guide, its exact version and its digital
  fingerprint, used to download and check everything before deployment. Pages are
  checked automatically to make sure nothing tries to load from the internet.
- **Security:** full-disk encryption unlocked by the computer's security chip (TPM);
  password-protected Wi-Fi and services; nothing reachable beyond the local network.
- **Installation:** a standard Ubuntu Linux installer with an automatic configuration,
  plus a content package (software, AI models, library), on one USB stick. Each kit
  generates its own passwords and keys on first start-up.

## Annex B. Glossary

| Term | Meaning |
|---|---|
| **KoboToolbox** | Free, open-source platform for designing forms, collecting data and managing it |
| **KoboCollect** | KoboToolbox's Android app for collecting data offline |
| **Enumerator** | A person collecting data, usually by interviewing respondents |
| **Open AI model** | An AI model whose files can be downloaded and run on your own computer, under a licence that allows it |
| **Transcription** | Turning an audio recording into written text |
| **Qualitative analysis** | Analysing open-ended answers and interviews, e.g. by theme |
| **AI assistant (agent)** | An AI that can use tools (here, KoboToolbox data and analysis tools) to complete a task described in plain language |
| **Word error rate** | Share of words a transcription gets wrong; lower is better |
| **Full-disk encryption** | Everything on the computer's storage is unreadable without the key |
| **TPM** | A security chip in the computer that holds the disk encryption key |
| **Sync** | Copying new data from one KoboToolbox server to another: from a field kit to a hub, or to a cloud server once a connection is available |
| **Dashboard** | A web page of charts, maps and figures that updates as new data arrives |
| **Knowledge base** | Documents the AI assistant searches to answer questions, citing the source (sometimes called RAG, retrieval-augmented generation) |
| **Hub kit** | A kit at a base location that combines data from several field kits for analysis and reporting |
| **Federated** | Several independent kits that each work on their own and share data with a hub when they can |
| **kobo-transfer** | Kobo's open-source tool for copying projects and submissions between KoboToolbox servers |
