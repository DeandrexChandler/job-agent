---
name: recruiter-outreach
description: After a job-agent run, find the university recruiter and an engineer or school alum at each company the user applied to, using ordinary web search (never LinkedIn itself), and write short LinkedIn connection notes and follow-up DMs for the user to send by hand. Keeps a log so nobody is drafted twice and stays under a daily cap. Never opens, signs in to, clicks on or sends anything on LinkedIn. Use when the user asks for recruiter or coffee chat outreach, recruiter DMs, or as the last step of job-run when outreach.enabled is true.
---

# recruiter-outreach

Python: `python3` (or `python_cmd` from `profile/preferences.yaml`). The script lives in this skill's `scripts/` folder. Workspace: `$JOB_AGENT_HOME` or `~/.job-agent/`.

## The one rule

The agent finds people and writes drafts. The user sends every message. Never open a linkedin.com page in the browser or with a fetch tool, never sign in, never click Connect or Message, never send anything. LinkedIn's User Agreement bans bots that add contacts or send messages, and the user's account is worth more than any one message. Search engine results that happen to link to LinkedIn profiles are fine to read; the profile pages themselves are not.

## Inputs

- `outreach` in `preferences.yaml`: `enabled`, `school`, `per_day`, `per_company`, `voice`.
- The jobs this run submitted or left Ready (company, title, fit), written to `state/outreach-jobs.json` as a list. Standalone use: the user names companies, or take the last week's rows from the tracker.
- The master resume and standing answers: the only source of facts about the user.
- Log: `state/outreach-log.json` (`scripts/outreach_log.py` reads and writes it).

## Steps

1. **Pick.** `python3 scripts/outreach_log.py pick --log <ws>/state/outreach-log.json --jobs <ws>/state/outreach-jobs.json --per-day <per_day> --per-company <per_company>`. It returns the companies to research today with how many people each still needs, best fit first. Stop when it returns an empty list.
2. **Search, per company,** with the web search tool only. Run a few short queries and stop once you have the people you need:
   - recruiter: `site:linkedin.com/in "<Company>" "university recruiter"`, then `"early career recruiter"`, `"campus recruiter"`, `"technical recruiter" intern`
   - alum: `site:linkedin.com/in "<Company>" "<school>" software engineer`
   - engineer on the team, when the posting names one: `site:linkedin.com/in "<Company>" "<team or product from the posting>" engineer`
   Prefer a university or early-career recruiter over a general one, and an alum over a random engineer. From each result use only what the result title and snippet show: name, current title and company, and the profile URL. Skip anyone whose snippet does not show them at that company now, anyone senior to the point a cold note is odd (VP and up), and anyone already in the log (step 4 refuses them anyway). If nothing fits after about four queries, note the company as "nobody found" and move on. Never guess a name or URL.
3. **Draft** for each person, from facts in the master resume and the search snippet only. Engineers and alums get questions, not asks: people answer someone curious about their work and ignore someone who wants a referral. So their drafts never mention the application, the role, a req ID, a referral or "a good word". The user brings that up themselves after a real chat.
   - **Connection note**, at most 200 characters (free LinkedIn accounts cap notes and may limit how many notes a month; the user can send without one).
     - Engineer or alum: open with one specific thing they did, taken from the snippet (a team, product, past role or move). Add the shared school only when the snippet shows it. Then one line on who the user is (a CS student at their school) and a plain "wondering if we could connect?". Example: "Hi Sam, I saw you went from Uber's self-driving team to building delivery robots at DoorDash! I'm a CS student at SDSU and was wondering if we could connect?"
     - Recruiter: name the role the user applied to and one real thing about the user that fits the posting.
   - **Follow-up DM** for after they accept, 2 to 4 short sentences.
     - Engineer or alum: tie their work to the user's interest in one line. Then ask one real question, for example what they would do if they were starting from square one again. End with a low-pressure ask: "if you have 5 minutes sometime, I'd love to hear what it's like working at <something personal from the snippet: their city, team, a career switch>". Keep it 5 minutes even though a chat runs longer, because a small ask gets a yes.
     - Recruiter: who the user is, the role and req ID, one relevant project in plain words, and whether the application can get a look or what the team looks for.
   - Voice: follow `outreach.voice` and the user's `voice/` profile when it exists. Sound like a student texting a professional they respect: plain words, contractions, no "I hope this finds you well", "passionate", "leverage", "excited to connect", "synergy", no emojis unless the user's voice uses them, no flattery about the person's career. Save each draft to a temp file and run `python3 ../your-voice/scripts/writecheck.py check <file> --max-chars 200` for notes (no `--max-chars` for DMs); fix what it flags and run it again.
   - One draft per person; never the same note to two people word for word.
4. **Record** each person: `python3 scripts/outreach_log.py record --log ... --company "<C>" --name "<N>" --url "<profile URL>" --role "<their title>" --kind recruiter|alum|engineer --job "<title applied to>"`. If it refuses, drop that draft.
5. **Write the day's file** `<ws>/outreach/<YYYY-MM-DD>.md` (append if it exists): one section per company with the job applied to, then per person: name, title, why them (recruiter, alum, engineer on the team), profile URL, the connection note in a code block, and the follow-up DM in a code block. End with the companies where nobody was found.
6. **Report** one line in the run summary: drafts written, companies covered, and the path to the day's file. No notification of its own.

## After the user sends

When the user says they sent, got a reply, or want to skip someone: `python3 scripts/outreach_log.py mark --log ... --url "<profile URL>" --status sent|replied|skip`. `list --status sent` shows who has not replied, for a follow-up draft about a week later (one follow-up at most, never more).

## Never

- Open, fetch, scroll, sign in to or act on linkedin.com, or use any LinkedIn API, export, or extension.
- Invent a fact about the user or the person, or claim a connection that does not exist ("we met at...", a shared school the snippet does not show).
- Draft to someone the log already holds, or more than `per_day` people in a day.
- Look up personal email addresses or phone numbers.
