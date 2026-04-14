# mgr4smb For Dummies

_A plain-English tour of the multi-agent chat assistant. No prior AI knowledge required. Short chapters, lots of analogies, minimal jargon._

---

## Chapter 1: What on earth is this thing?

Imagine you run a home-services company — say, cleaning. People call or chat in all day long. Some want to book a cleaning. Some want to reschedule. Some are asking "what areas do you serve?" Some are existing customers checking on next week's visit.

Instead of having a human receptionist handle every single call, **mgr4smb is a robot receptionist**. It lives behind a chat window on your website. A customer types in, it figures out what they want, and either answers them directly or does the work (book the appointment, look up their job, etc.) by talking to the tools you already use — GoHighLevel (your CRM / calendar) and Jobber (your field-service software).

> 💡 **The key idea:** one chat window, one web address, but behind the scenes there's a whole team of specialist "robots" taking turns. The customer never sees that — they just see one helpful assistant.

---

## Chapter 2: Meet the team (the 7 agents)

Under the hood, mgr4smb is not one big robot. It's seven small robots, each really good at one thing. Think of them as the staff at a small office:

| Agent | Office role |
|---|---|
| **Orchestrator** | The receptionist. Answers the door, figures out what you need, sends you to the right person. Never tries to answer detail questions themselves. |
| **Greeting** | The person who checks you against the visitor log and says "Welcome back, David!" or "Hi, nice to meet you!". |
| **General Info** | The office manager who knows the services, prices, hours, and policies. Anything from the company handbook. |
| **Booking** | The scheduler. Checks the calendar, finds open slots, writes the appointment down. |
| **OTP** | The security guard. Before they let you change anything sensitive, they send a 6-digit code to your email to make sure you are who you say you are. |
| **GHL Support** | The customer-service rep who handles YOUR existing appointments — view, reschedule, cancel. |
| **Jobber Support** | The foreman who knows about your actual jobs and visits: "your cleaning is scheduled for Tuesday at the Westwood house". |

> 📝 **Why so many?** Because "do everything" robots get confused. A specialist with one clear job does it well. The receptionist (Orchestrator) picks the right specialist for each customer, every turn.

---

## Chapter 3: How a conversation actually flows

Let's walk through a real scenario. You're a customer. You type:

> **You:** "Hi, I'd like to book a cleaning for my house next Tuesday."

Here's what happens, step by step:

1. **Chat UI → FastAPI.** Your message arrives at our server. The server first checks you have a valid "badge" (JWT token). You do.

2. **Orchestrator wakes up.** It reads your message and thinks, "I don't have your email or phone yet. I need that before I can route this." So it replies: *"Before I connect you, can I get your email and phone number?"*

3. **You reply** with your email and phone.

4. **Orchestrator calls Greeting.** Greeting looks you up in GoHighLevel. If you're a returning customer, it says "Welcome back, David!". If not, "Thanks for contacting us!". Orchestrator relays this to you.

5. **Orchestrator picks a specialist.** Your original message was about booking → it hands off to **Booking**.

6. **Booking does its thing.** Asks a few clarifying questions (what service, what timezone), then checks the GoHighLevel calendar and gives you open slots.

7. **You pick a slot.** Say, "I'd like slot 4 (12:00 PM)".

8. **Booking calls OTP.** Before finalizing anything, the security guard sends a 6-digit code to your email. You check your inbox, grab the code, type it in.

9. **OTP verifies the code.** Returns "VERIFIED".

10. **Booking writes the appointment** to GoHighLevel. Done. You get a confirmation.

> 🎯 **The magic trick:** every specialist sees the whole conversation up to that point. When Booking calls OTP, OTP already knows your email, your name, and that you just picked slot 4. Nobody asks you anything twice.

---

## Chapter 4: Your identity, protected twice

The system cares a LOT about making sure "you" really is you before it changes any data. That matters because someone who knew your email could otherwise reschedule your appointment just by chatting in.

There are two locks:

### Lock #1 — The badge (JWT)
When your company deploys mgr4smb, they issue you a **JWT token**. This proves you're an authorized CLIENT of the company (not a random stranger). Every message you send carries this badge. If the badge is missing, forged, or expired, you get a polite "not authorized" response and nothing happens.

Think of it like an office building's keycard. You need it just to walk in the door.

### Lock #2 — The one-time code (OTP)
But a keycard isn't enough for a specific individual's data. So before the system touches YOUR appointments (not just lets you chat), it also emails a fresh 6-digit code to the email on file and asks you to type it in. This proves you can read that email account.

**The system is deliberately strict here:**
- The code is emailed **only once per conversation**. If you mis-type it, you get exactly one retry. Three failed codes total and the assistant politely stops and suggests you call a real person.
- Once verified, the assistant remembers for the rest of your session — you won't be asked to verify again even if you switch topics.

> ⚠️ **Remember:** There's no way to "peek" at your code. It was already sent to your email. If you lost that email, start a new chat — don't ask for a resend (the system is designed to refuse).

---

## Chapter 5: Where the brain comes from

So how does the robot understand what you're saying? It uses **Google Gemini** (specifically the "2.5 Flash" model). Gemini is a large language model — the same kind of technology behind ChatGPT. Every time an agent needs to "think", it's actually sending your conversation to Gemini and getting back a response.

But Gemini on its own doesn't know anything about YOUR company. So when General Info is asked "what services do you offer?", it doesn't ask Gemini to guess. Instead:

1. It takes your question.
2. It asks Gemini to turn the question into a list of numbers (an "embedding").
3. It uses those numbers to search your company's **knowledge base** (a MongoDB database of company info).
4. It finds the passage that's most similar to your question.
5. It sends just that passage, plus your question, back to Gemini, which then writes the answer.

> 📚 **In plain English:** it's like a librarian who looks up the right page before answering, instead of guessing from memory. Much more accurate, and grounded in YOUR company's actual info.

---

## Chapter 6: How it remembers you across time

Every conversation has a unique `session_id`. When you type a message, that ID goes along with it. On the server, there's a **checkpointer** — a fancy word for "a big filing cabinet" — that saves the full conversation (your messages + the robot's replies + what it did) to MongoDB, filed under that session ID.

So if you close your browser tab and come back tomorrow (with the same `session_id`), the assistant picks up right where you left off. It remembers your email, that you were already verified, what service you were asking about, everything.

And if you start a fresh conversation tomorrow? You get a new `session_id` — a clean slate. The robot doesn't accidentally mix up different customers' conversations.

> 🗂️ **Two filing cabinets, actually:**
> - **Knowledge base** (company Q&A content, set up once)
> - **Checkpoints** (live conversations, growing constantly)
>
> Separate databases, separate purposes, separate collections.

---

## Chapter 7: The outside world it talks to

mgr4smb doesn't try to be a CRM, a calendar, or a job board on its own. It plugs into the tools you already have:

| Service | What it stores | What mgr4smb uses it for |
|---|---|---|
| **GoHighLevel** (GHL) | Contacts, calendar, phone numbers, marketing | Looking up callers, booking/cancelling appointments, sending OTP codes via email workflows |
| **Jobber** | Clients, properties (addresses), jobs, visits | Checking what work is scheduled, creating new service jobs |
| **MongoDB Atlas** | Company knowledge base + conversation history | Answering FAQs, remembering your chats |
| **Google Gemini** | _(nothing — stateless)_ | The actual "thinking" for every agent |
| **LangSmith** | Debugging traces (optional) | Lets developers see exactly what went wrong when something breaks |

When you ask to book, mgr4smb writes to GoHighLevel's calendar. When you ask about your jobs, it queries Jobber's database. When someone says "I want a recurring cleaning", it creates a Jobber client + property + job. No data lives inside mgr4smb itself — everything important is in the external systems you can already see and manage.

> 🔌 **This is why the system can be swapped or extended.** Don't like Gemini? The LLM is a single module. Switch CRMs? The GHL tool is a single module. Each external system lives behind a thin wrapper that's easy to replace.

---

## Chapter 8: What makes it extra clever

A few design choices that took real work to get right:

### It doesn't recycle old responses
If the robot's most recent turn comes back empty (yeah, AI sometimes does that), mgr4smb doesn't secretly show you the last turn's message instead. It recognizes the empty response, quietly retries once with a nudge, and if that still fails it says "I wasn't able to produce a response — could you rephrase?" You always know what the robot actually just did.

### Slot picking "just works"
If the robot offers "1. 9 AM / 2. 10 AM / 3. 11 AM / 4. 12 PM" and you type just `4`, it knows you mean slot 4. You don't have to say "I'd like slot number four at 12 PM please."

### Services come from YOUR words, not a menu
If you say "I need a cleaning, a deep clean, and move-out service", the robot treats that as the service list for your appointment. It doesn't present those back to you as a numbered menu and make you pick one. You already told it what you want.

### The calendar event gets a real summary
When the robot finishes booking, the appointment doesn't just say "Consultation". It gets a 1–3 sentence note describing who you are, what you want to discuss, and any context you shared. Whoever opens the calendar later sees real context, not just a time slot.

### The OTP email only fires once
The system is careful to NEVER resend a verification code in the same conversation. Why? Because the workflow that sends the email fires every time the code-field changes. If we "cleared" the code after success, the workflow would fire again with an empty code — you'd get a blank email. Instead the system marks the code as expired (back-dating the timestamp) without touching the code field itself. Exactly one email per verification.

---

## Chapter 9: The full cast of characters (glossary)

Quick definitions so nothing feels mysterious:

| Term | In plain English |
|---|---|
| **Agent** | A specialist robot with one job. In mgr4smb there are 7. |
| **LLM** | Large Language Model — the AI that generates text. We use Google Gemini. |
| **Tool** | A function an agent can call to get something done (look up a contact, write to a calendar, etc.). |
| **Orchestrator** | The top-level agent that routes you to the right specialist. |
| **Session / thread** | One continuous conversation, identified by a `session_id` (a UUID). Survives across turns, across browser refreshes, across the server restarting. |
| **Checkpointer** | The filing cabinet that saves every turn of every session into MongoDB. |
| **JWT** | JSON Web Token. The digital "badge" that proves you're an authorized client of the company. |
| **OTP** | One-Time Password. The 6-digit code emailed to you for identity verification. |
| **Delegation** | When one agent calls another agent to handle a sub-task. Booking calls OTP to verify identity; GHL Support calls Booking for the rebook step of a reschedule. |
| **Injected state** | The trick that lets a sub-agent see the PARENT agent's full conversation history, so nobody asks you anything twice. |
| **Embedding** | Turning a sentence into a list of numbers so the computer can compare meanings. |
| **Vector search** | Finding the knowledge base passage whose embedding is closest to the question's embedding. |

---

## Chapter 10: Playing with it

Two ways to poke at the system:

1. **The chat window** — `http://localhost:8000/chat-ui/` once the server is running. You need a JWT (issue one from `./menu.sh` → "Create new client + JWT").

2. **The interactive architecture map** — open `mgr4smb-architecture.html` in a browser. Click components, hover over the arrows, switch between presets like "New Booking" or "Reschedule Flow" to see which parts of the system light up for each scenario.

Both are safe to explore. The chat just talks to your dev environment. The map is a diagram — clicking doesn't break anything.

---

## Chapter 11: "But what if it breaks?"

Three things to know:

### If an agent gives up
Sometimes Gemini returns an empty response. The system retries once quietly, then gives a polite "I wasn't able to respond" message. The conversation continues — the NEXT turn usually works fine.

### If a downstream service is down
If GoHighLevel goes down mid-booking, you get a clear error ("GHL service unavailable") and the booking is NOT confirmed. MongoDB going down triggers the same kind of graceful refusal. No silent failures.

### If you need to see what happened
Every conversation is traced in LangSmith. A developer can filter by your `session_id` and see: what you said, what the orchestrator decided, which agent it called, what tools fired, what each of them returned, and how long each step took. Nothing is hidden.

> 🧭 **Rule of thumb:** any error your chat assistant shows you is a REAL error. It doesn't bluff. If something appears confirmed, it actually happened (in GHL or Jobber). If something says "not confirmed", the remote system wasn't touched.

---

## That's it

You now understand mgr4smb better than most people who've worked on it a week.

If you remember one thing, let it be this: **mgr4smb is a team of specialists who pass a single shared notebook between them. The receptionist routes; everyone else handles one thing well; and nobody skips the security guard before touching your data.**

Everything else — the MongoDB, the Gemini, the JWT, the OAuth — is just the plumbing that makes those three ideas actually work.
