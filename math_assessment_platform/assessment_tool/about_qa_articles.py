"""HTML bodies and tags for public About-linked Q&A articles.

Used by ``seed_about_qa_articles``. Titles must match ``about.ABOUT_ARTICLE_TITLES``.
"""

from __future__ import annotations

from . import about as about_mod

SHARED_TAGS = ("about", "map-features")


def _p(*paragraphs: str) -> str:
    return "".join(f"<p>{text}</p>" for text in paragraphs)


def _h2(text: str) -> str:
    return f"<h2>{text}</h2>"


def _h3(text: str) -> str:
    return f"<h3>{text}</h3>"


def _ul(items: list[str]) -> str:
    return "<ul>" + "".join(f"<li>{item}</li>" for item in items) + "</ul>"


def _faq(pairs: list[tuple[str, str]]) -> str:
    parts = [_h2("FAQ")]
    for q, a in pairs:
        parts.append(_h3(q))
        parts.append(f"<p>{a}</p>")
    return "".join(parts)


ARTICLE_SPECS: list[dict] = [
    {
        "title": about_mod.TITLE_MAP_AND_FLIPPEDMATH,
        "tags": SHARED_TAGS + ("flippedmath", "getting-started"),
        "body": "".join(
            [
                _p(
                    "The <strong>Math Assessment Platform (MAP)</strong> is where teachers "
                    "build, deliver, and grade rigorous math assessments—online and on paper—"
                    "with tools designed around real classroom workflows."
                ),
                _p(
                    "Assessments created on MAP are part of "
                    "<a href=\"https://flippedmath.com\">flippedmath.com</a>. "
                    "MAP is the assessment engine in that instructional ecosystem: "
                    "the place where problem design, delivery integrity, and grading come together."
                ),
                _h2("Who MAP is for"),
                _ul(
                    [
                        "<strong>Teachers</strong> — author parametric problems, assemble assessments, "
                        "invite students, grade, and manage courses.",
                        "<strong>Students</strong> — take assessments with autosave, timers, and clear "
                        "status when work is locked or submitted.",
                        "<strong>Parents</strong> — receive grade-access invites to follow a student's "
                        "progress in participating courses.",
                        "<strong>IT Support</strong> — administer help content, credits, tickets, and "
                        "platform operations.",
                    ]
                ),
                _h2("Early access"),
                _p(
                    "MAP is live for early testing while remaining features are finished. "
                    "Core workflows—authoring, delivery, grading, explorer sharing, and course "
                    "management—are already usable. The public Q&amp;A and Contact pages are "
                    "available whether or not you have an account."
                ),
                _h2("Where to go next"),
                _p(
                    "Use the <strong>About</strong> page for a short tour of capabilities, then "
                    "open the linked Q&amp;A articles for deep detail. Teachers can register, "
                    "sign in, and start building in Workspace and Courses."
                ),
                _faq(
                    [
                        (
                            "Is MAP a separate product from flippedmath.com?",
                            "MAP is the assessment platform in the flippedmath.com ecosystem. "
                            "Assessments you create here belong in that broader instructional story.",
                        ),
                        (
                            "Do I need an account to read help articles?",
                            "No. Public Q&amp;A articles—including this one—are readable without signing in.",
                        ),
                    ]
                ),
            ]
        ),
    },
    {
        "title": about_mod.TITLE_AUTHORING,
        "tags": SHARED_TAGS + ("authoring", "problems", "parametric", "workspace"),
        "body": "".join(
            [
                _p(
                    "Most quiz tools ask you to type a static question and a single answer. "
                    "<strong>MAP's problem workspace is different</strong>: you author a "
                    "<em>generator</em>—linked variables, display text, and answer fields—so one "
                    "problem can produce many valid instances with answers that still check correctly."
                ),
                _h2("The problem workspace"),
                _p(
                    "Open a problem from the Explorer or from assessment setup. The workspace "
                    "combines a rich content canvas (text, formatting, images, tables) with a "
                    "structured graph of <strong>entities</strong>: dynamic values and answer inputs "
                    "that reference each other."
                ),
                _h2("Dynamic variables (examples)"),
                _p(
                    "Entity types let you define the moving parts of a problem. Depending on what "
                    "you need, you can work with ideas such as:"
                ),
                _ul(
                    [
                        "Random integers and derived numeric quantities",
                        "Formulas that evaluate from other entities",
                        "Matrices and structured numeric layouts",
                        "Graphs, slope fields, and geometry-style interactions",
                        "Number-theory style helpers (for example prime-factor style quantities)",
                    ]
                ),
                _p(
                    "Because entities can reference each other, changing an upstream random value "
                    "updates dependent displays and expected answers together—so the instance stays consistent."
                ),
                _h2("Answer fields that match the math"),
                _p(
                    "Students do not have to squeeze every response into a single text box. "
                    "MAP supports answer patterns suited to mathematics, including:"
                ),
                _ul(
                    [
                        "Numeric responses with automatic checking",
                        "Multiple choice",
                        "Matrix entry",
                        "Graph interactions (for example between points)",
                        "Slope-field and canvas-style work",
                        "Long-answer / open response when human review is needed",
                    ]
                ),
                _h2("Why this is powerful"),
                _ul(
                    [
                        "<strong>Author once, reuse many times</strong> — regenerate unique versions "
                        "for practice, homework, or secure testing.",
                        "<strong>Auto-checkable structure</strong> — when answers are tied to the same "
                        "entity graph, grading can verify the instance the student actually received.",
                        "<strong>Real math media</strong> — Quill content, images, and visual answer "
                        "types keep problems from being “text-only quizzes.”",
                    ]
                ),
                _h2("Where teachers use it"),
                _p(
                    "Create and refine problems in your <strong>Workspace</strong> or inside a course "
                    "assessment setup. Preview and practice flows help you verify generators before "
                    "students see them."
                ),
                _faq(
                    [
                        (
                            "Is every answer auto-graded?",
                            "Numeric and many structured fields can be auto-checked. Canvas and "
                            "long-answer style work is designed for teacher review (see hybrid grading).",
                        ),
                        (
                            "Can I still write ordinary static questions?",
                            "Yes. You can keep values fixed when you want a single canonical form—"
                            "parametric tools are there when you need variation and integrity.",
                        ),
                    ]
                ),
            ]
        ),
    },
    {
        "title": about_mod.TITLE_BLUEPRINTS,
        "tags": SHARED_TAGS + ("assessments", "sections", "problem-sets", "randomization"),
        "body": "".join(
            [
                _p(
                    "In MAP, an assessment is not just a scrambled list of questions. It is a "
                    "<strong>blueprint</strong>: nested structure that mirrors how teachers already "
                    "think about tests—sections, problem sets, and individual items."
                ),
                _h2("The hierarchy"),
                _ul(
                    [
                        "<strong>Course</strong> — the classroom container under your Courses folder",
                        "<strong>Assessment</strong> — a deliverable unit (quiz, test, assignment)",
                        "<strong>Section (AQG)</strong> — Assessment Question Group: a named part of the test",
                        "<strong>Problems and problem sets (CQD)</strong> — items or banks under a section",
                    ]
                ),
                _h2("Sections (AQG)"),
                _p(
                    "Sections let you organize “Part A / Part B,” skill clusters, or timed segments "
                    "of a larger exam. You can rename and reorder sections as the blueprint evolves."
                ),
                _h2("Randomized problem sets (CQD)"),
                _p(
                    "A <strong>Custom Question Distribution</strong> (problem set) holds a pool of "
                    "problems and draws a suggested count for each student instance. That is bank-style "
                    "randomization <em>inside</em> a structured assessment—not merely shuffling a fixed list."
                ),
                _p(
                    "Use problem sets when you want variety across students while keeping the same "
                    "section structure and difficulty profile."
                ),
                _h2("Setup workflow"),
                _p(
                    "From a course’s Assessments page, open <strong>Setup Questions</strong> for an "
                    "assessment. There you create sections, add problems, attach problem sets, and "
                    "reorganize the tree until the blueprint matches your intent."
                ),
                _h2("Why it matters"),
                _ul(
                    [
                        "Blueprints stay readable for co-teachers and future you",
                        "Banks reduce item exposure without abandoning structure",
                        "The same hierarchy powers practice tests, student takes, print, and grading views",
                    ]
                ),
                _faq(
                    [
                        (
                            "Can a section mix fixed problems and a bank?",
                            "Yes. Sections can contain direct problems and problem sets together, "
                            "so some items stay fixed while others draw from a pool.",
                        ),
                        (
                            "Where does this live in Explorer?",
                            "The same course → assessment → section → problem tree appears in the "
                            "Explorer, so content stays navigable outside the course UI.",
                        ),
                    ]
                ),
            ]
        ),
    },
    {
        "title": about_mod.TITLE_PRACTICE_TEST,
        "tags": SHARED_TAGS + ("assessments", "practice-test", "teacher-workflow"),
        "body": "".join(
            [
                _p(
                    "Parametric assessments are powerful—and easy to get slightly wrong. MAP gives "
                    "teachers a <strong>practice test</strong> path so you can assemble a generated "
                    "instance, take it, and grade it <em>before</em> students ever see the assessment."
                ),
                _h2("What practice test does"),
                _ul(
                    [
                        "Builds an instance from your current blueprint (sections, banks, generators)",
                        "Lets you experience the student-facing flow privately",
                        "Surfaces broken links, impossible constraints, or awkward wording early",
                    ]
                ),
                _h2("When to use it"),
                _p(
                    "Run a practice test after major blueprint changes, after editing parametric "
                    "entities, or before flipping status from hidden to open/upcoming. It is especially "
                    "valuable when using randomized problem sets or synchronized forms."
                ),
                _h2("How to start"),
                _p(
                    "Open the assessment’s setup page and use the practice-test action. Complete the "
                    "run as if you were a student, then review grading behavior for auto-checked and "
                    "manual fields."
                ),
                _h2("Why it matters"),
                _p(
                    "Catching a generator bug five minutes before class is painful. Practice tests "
                    "turn MAP’s generative strength into a controlled release process."
                ),
                _faq(
                    [
                        (
                            "Does a practice test count as a student submission?",
                            "No. It is a teacher workflow for validating the blueprint, separate from "
                            "class attempts.",
                        ),
                        (
                            "Should I practice after every tiny edit?",
                            "Not always—but after structural or entity changes, a quick practice run "
                            "is cheap insurance.",
                        ),
                    ]
                ),
            ]
        ),
    },
    {
        "title": about_mod.TITLE_SYNC_PRINT,
        "tags": SHARED_TAGS + ("delivery", "synchronized-tests", "printing", "integrity"),
        "body": "".join(
            [
                _p(
                    "MAP lets you choose the fairness model that fits the moment: "
                    "<strong>one shared form for the class</strong>, or "
                    "<strong>unique instances per student</strong>—and it can freeze a form for "
                    "<strong>paper printing with a match-key answer key</strong>."
                ),
                _h2("Synchronized tests"),
                _p(
                    "When synchronization is enabled, students share a frozen form (the same random "
                    "draws). That is ideal when you want everyone arguing about the same numbers on "
                    "the board, comparing work fairly, or walking through solutions together afterward."
                ),
                _h2("Unique instances"),
                _p(
                    "Without a synchronized freeze—or when generation creates per-student forms—"
                    "each student can receive a different valid instance of the same blueprint. "
                    "That reduces casual copying while preserving the same skills and structure."
                ),
                _h2("Printing and match-key answer keys"),
                _p(
                    "Teachers can print a frozen assessment instance to PDF through the browser print "
                    "flow, along with an answer key tied to that instance via a match key. The key is "
                    "designed to stay unambiguous so paper packets and keys stay paired correctly."
                ),
                _p(
                    "<strong>Note:</strong> Print capability is available to teachers whose accounts "
                    "are unlocked with seat credits (same unlock family as inviting students). "
                    "If print actions are unavailable, check your Credits balance / unlock status "
                    "under Account Settings."
                ),
                _h2("Choosing a mode"),
                _ul(
                    [
                        "<strong>Sync</strong> — shared discussion, common review, fair comparison",
                        "<strong>Unique</strong> — higher integrity for independent work",
                        "<strong>Print</strong> — substitute coverage, accommodations, or offline periods",
                    ]
                ),
                _faq(
                    [
                        (
                            "Can I switch modes later?",
                            "Delivery options are teacher-controlled on the assessment. Change them "
                            "before students start when possible; practice-test after changes.",
                        ),
                        (
                            "Does print work with synchronized forms?",
                            "Yes. Printing is built to respect the frozen instance model so paper "
                            "and digital stay aligned.",
                        ),
                    ]
                ),
            ]
        ),
    },
    {
        "title": about_mod.TITLE_FOCUS_LOCK,
        "tags": SHARED_TAGS + ("integrity", "focus-lock", "proctoring", "dashboard"),
        "body": "".join(
            [
                _p(
                    "MAP includes a <strong>focus-leave lock</strong>: if a student leaves the "
                    "assessment tab during a take, the attempt can lock until a teacher unlocks it. "
                    "This is integrity support without installing a third-party lockdown browser or spyware."
                ),
                _h2("What students experience"),
                _p(
                    "During an in-progress attempt, leaving the page/tab can trigger a locked state. "
                    "The student sees that work is paused and that a teacher must unlock before they continue."
                ),
                _h2("What teachers see"),
                _ul(
                    [
                        "A live attention signal on the teacher dashboard for students awaiting unlock",
                        "Unlock actions from grading / attempt management workflows",
                        "A clear operational loop: notice → decide → unlock → student continues",
                    ]
                ),
                _h2("What it is—and is not"),
                _ul(
                    [
                        "<strong>It is</strong> a lightweight proctoring cue tied to focus leave",
                        "<strong>It is not</strong> remote desktop monitoring, webcam recording, or "
                        "a claim of perfect cheat-proofing",
                    ]
                ),
                _p(
                    "Use it with clear classroom norms. Pair it with unique instances, timed windows, "
                    "or synchronized forms depending on your integrity goals."
                ),
                _faq(
                    [
                        (
                            "Can a student unlock themselves?",
                            "No. Unlock is a teacher (or authorized staff) action after reviewing the situation.",
                        ),
                        (
                            "Does every assessment use focus lock?",
                            "Delivery options control integrity-related behavior per assessment. "
                            "Configure the assessment to match your policy.",
                        ),
                    ]
                ),
            ]
        ),
    },
    {
        "title": about_mod.TITLE_WINDOWS_TIMERS,
        "tags": SHARED_TAGS + ("delivery", "scheduling", "timers"),
        "body": "".join(
            [
                _p(
                    "Delivery in MAP is more than an on/off switch. Teachers control "
                    "<strong>lifecycle status</strong>, optional <strong>auto-open windows</strong>, "
                    "<strong>timer modes</strong>, and <strong>autosave</strong> while students work."
                ),
                _h2("Assessment status lifecycle"),
                _ul(
                    [
                        "<strong>Hidden</strong> — not visible to students; safe for building",
                        "<strong>Open</strong> — available for students to take",
                        "<strong>Upcoming</strong> — scheduled to open during a start–end window; "
                        "students may experience it as open while the window is active",
                        "<strong>Closed</strong> — class-wide taking has ended (individual retakes "
                        "can still be managed separately)",
                    ]
                ),
                _h2("Auto-open windows"),
                _p(
                    "For upcoming assessments, set start and end timestamps. MAP can open and later "
                    "close the window according to that schedule, so you are not watching the clock "
                    "to flip a dropdown at period start."
                ),
                _h2("Timers"),
                _p(
                    "Assessment delivery options include flexible timing—such as count-up awareness "
                    "or countdown toward an end time / time limit—so a quiz, a block-period exam, and "
                    "a short skills check can each feel right."
                ),
                _h2("Autosave"),
                _p(
                    "During a take, student work autosaves. That reduces panic from accidental refresh "
                    "and makes timed assessments more humane."
                ),
                _h2("Generation while opening"),
                _p(
                    "When unique student forms are assembling, teachers may see generation progress "
                    "on the assessments list. Wait for generation to finish before expecting every "
                    "student to start cleanly."
                ),
                _faq(
                    [
                        (
                            "Can I still open manually?",
                            "Yes. Status can be set directly when you do not need a scheduled window.",
                        ),
                        (
                            "What if the window ends mid-attempt?",
                            "Closing behavior follows assessment status and retake rules. Prefer "
                            "windows that match period length, and use retakes for exceptions.",
                        ),
                    ]
                ),
            ]
        ),
    },
    {
        "title": about_mod.TITLE_HYBRID_GRADING,
        "tags": SHARED_TAGS + ("grading", "auto-grade", "manual-grading"),
        "body": "".join(
            [
                _p(
                    "MAP is built for <strong>hybrid grading</strong>: automatically check what the "
                    "entity system can verify, then give teachers fast tools for everything that still "
                    "needs a human."
                ),
                _h2("What auto-grades well"),
                _p(
                    "Structured answers tied to parametric entities—numeric results, many constrained "
                    "formats, and similarly checkable fields—can be evaluated against the instance the "
                    "student received."
                ),
                _h2("What needs manual attention"),
                _p(
                    "Canvas work, long answers, and other open-ended responses are flagged for teacher "
                    "review. The dashboard can surface when manual grading is still required so nothing "
                    "sits invisible in a queue."
                ),
                _h2("Question-batch grading"),
                _p(
                    "Instead of only grading student-by-student, teachers can grade the <strong>same "
                    "question slot across the class</strong>. That is dramatically faster for shared "
                    "structure—especially when many students answered the same blueprint item in "
                    "different numeric costumes."
                ),
                _h2("Attempt review and overrides"),
                _p(
                    "Open an attempt review to inspect responses, adjust scores, and finalize. Overrides "
                    "exist because real classrooms need judgment—partial credit, misread work, or "
                    "special cases."
                ),
                _h2("Why it scales"),
                _ul(
                    [
                        "Auto-grade removes busywork on deterministic fields",
                        "Batch views keep open-ended grading focused",
                        "Dashboard signals prevent forgotten piles of ungraded work",
                    ]
                ),
                _faq(
                    [
                        (
                            "Do students see grades immediately?",
                            "Release behavior is configurable (see the grades-control article). "
                            "Auto-grade does not force instant publication.",
                        ),
                        (
                            "Can I regrade after release?",
                            "Teachers can revisit attempts and adjust; communicate policy clearly when scores change.",
                        ),
                    ]
                ),
            ]
        ),
    },
    {
        "title": about_mod.TITLE_GRADES_CONTROL,
        "tags": SHARED_TAGS + ("grading", "retakes", "grade-release", "policies"),
        "body": "".join(
            [
                _p(
                    "Grading policy is not one-size-fits-all. MAP gives teachers control over "
                    "<strong>weights</strong>, <strong>curves</strong>, <strong>retakes</strong>, and "
                    "<strong>how scores are released</strong> to students."
                ),
                _h2("Weights and scoring models"),
                _p(
                    "Choose how items contribute—such as summing points versus equal-weight treatment—"
                    "so a multi-part exam matches your syllabus, not a platform default."
                ),
                _h2("Curves"),
                _p(
                    "When you need a class-level adjustment, curve controls let you reshape outcomes "
                    "without rebuilding the assessment."
                ),
                _h2("Retakes"),
                _ul(
                    [
                        "Class policies for which attempt counts (for example highest or latest)",
                        "<strong>Per-student retake grants</strong> — reopen opportunity for one learner "
                        "without reopening the entire class",
                        "Dashboard visibility for active retakes so teachers see who is still working",
                    ]
                ),
                _h2("Score release"),
                _p(
                    "Control whether students see scores only, or a fuller review of their submission. "
                    "That lets you release quickly after auto-grade while holding detailed solutions "
                    "until the period is done—or the opposite, depending on pedagogy."
                ),
                _h2("Performance views"),
                _p(
                    "Course grades views help you inspect assessment performance across the class, "
                    "not only individual attempts—useful for reteaching decisions."
                ),
                _faq(
                    [
                        (
                            "Can parents see grades?",
                            "When you invite a parent to a course for grade access, they can follow "
                            "visibility appropriate to that invite (see co-teachers &amp; parents).",
                        ),
                        (
                            "Do closed assessments block retakes?",
                            "Class-wide closed status stops ordinary new takes; individual retake "
                            "grants remain the tool for exceptions.",
                        ),
                    ]
                ),
            ]
        ),
    },
    {
        "title": about_mod.TITLE_EXPLORER,
        "tags": SHARED_TAGS + ("explorer", "collaboration", "public-library", "sharing"),
        "body": "".join(
            [
                _p(
                    "MAP’s <strong>Explorer</strong> is a finder-style content browser for the full "
                    "hierarchy of courses, assessments, sections, problem sets, and problems—plus "
                    "Workspace drafts, Collaboration shares, Public Library, and Trash."
                ),
                _h2("Why a hierarchy matters"),
                _p(
                    "Math departments do not think in flat quiz lists. Explorer keeps the same "
                    "structural tree you build in assessment setup, so content stays navigable, "
                    "movable, and shareable."
                ),
                _h2("Workspace vs Courses"),
                _ul(
                    [
                        "<strong>Workspace</strong> — drafting and personal organization",
                        "<strong>Courses</strong> — published classroom course trees you own",
                        "Move assessments and related content into owned courses when ready; "
                        "moving a whole course into Courses parks it as closed until you reactivate",
                    ]
                ),
                _h2("Sharing and collaboration"),
                _p(
                    "Share folders or items with read or edit access. Permission groups support "
                    "department-style collaboration (including nested group structure). Collaborators "
                    "with read access can open items in view mode and <strong>copy to Workspace</strong> "
                    "to work locally."
                ),
                _p(
                    "Private collaboration groups require an unlocked teacher account (seat credits). "
                    "Public Library browsing remains available more broadly."
                ),
                _h2("Public Library"),
                _p(
                    "The Public Library surfaces shared content for teachers to browse. Open items in "
                    "view mode or copy them into your Workspace to adapt—without editing the shared original."
                ),
                _h2("View mode vs edit mode"),
                _p(
                    "Explorer open actions respect permissions: read-only collaborators get view mode; "
                    "edit access enables editing. This keeps shared libraries safer during review."
                ),
                _faq(
                    [
                        (
                            "Can I put arbitrary folders under Courses?",
                            "Courses is reserved for course trees. Place assessments and nested "
                            "structure inside a course you own, not loose plain folders.",
                        ),
                        (
                            "What happens if I delete shared content?",
                            "Unshare (or remove collaborators) before deleting shared roots. Explorer "
                            "warns when something is still shared.",
                        ),
                    ]
                ),
            ]
        ),
    },
    {
        "title": about_mod.TITLE_CREDITS,
        "tags": SHARED_TAGS + ("credits", "invites", "teachers"),
        "body": "".join(
            [
                _p(
                    "MAP uses a <strong>seat-credit</strong> system so classroom capacity is explicit: "
                    "credits unlock teacher capabilities, and inviting a student spends a seat token."
                ),
                _h2("What unlock means"),
                _p(
                    "Teachers with no usable credit history start in a locked state aimed at exploration—"
                    "for example limited course capacity and no student invites. Unlocking (via balance "
                    "or prior unreimbursed seat spend) enables inviting students, broader course use, "
                    "and private collaboration groups. Print capability is also tied to unlock."
                ),
                _h2("Spending seats on invites"),
                _p(
                    "When you invite a student into a course, a credit is spent for that seat. That "
                    "makes procurement and classroom size easy to reason about for schools and teachers."
                ),
                _h2("Reimbursement"),
                _p(
                    "If a student is removed early under the platform’s reimbursement rules (for example "
                    "within about a week of enrollment), the seat can be credited back. Voiding unused "
                    "invites likewise returns capacity when appropriate."
                ),
                _h2("Getting credits"),
                _ul(
                    [
                        "<strong>Buy credits</strong> — checkout-style purchase that grants credits promptly",
                        "<strong>Request allotment</strong> — submit a request (with note and/or invoice) "
                        "for IT verification before credits are granted",
                        "<strong>Teacher transfer</strong> — send credits to another teacher when allowed",
                        "<strong>IT grant/revoke</strong> — admins can adjust balances with audit history",
                    ]
                ),
                _h2("Where to manage this"),
                _p(
                    "Teachers use the Credits area under Account Settings. Course management surfaces "
                    "seat context when inviting. IT Support has a Credits admin view for grants, "
                    "pending allotments, and purchase history."
                ),
                _faq(
                    [
                        (
                            "Do unused credits expire automatically?",
                            "Unused balance is not designed as a short auto-expiring token; follow "
                            "your institution’s purchase terms for any external billing rules.",
                        ),
                        (
                            "Can I invite before unlocking?",
                            "Student invites require unlock / available credits. Explore authoring "
                            "in Workspace first if you are still evaluating the platform.",
                        ),
                    ]
                ),
            ]
        ),
    },
    {
        "title": about_mod.TITLE_ROLES,
        "tags": SHARED_TAGS + ("courses", "parents", "co-teachers", "roles"),
        "body": "".join(
            [
                _p(
                    "A course in MAP is a living classroom object: students, optional co-teachers, "
                    "parent grade access, and a lifecycle from developing work to closed archive."
                ),
                _h2("Students"),
                _p(
                    "Invite students by the platform’s invite flow (email/username patterns supported "
                    "in course management). Accepted invites enroll the student and spend seat credits "
                    "as described in the credits article."
                ),
                _h2("Co-teachers"),
                _p(
                    "Bring colleagues into a course as co-teachers so setup, grading, and day-to-day "
                    "operations are shared. Transfer patterns exist for handing primary ownership when "
                    "staffing changes."
                ),
                _h2("Parents"),
                _p(
                    "Parent invites grant grade-visibility access appropriate to the course—so families "
                    "can follow outcomes without needing a full teacher account or student credentials."
                ),
                _h2("Role-aware dashboard"),
                _p(
                    "The home dashboard adapts: teachers see operational cards (courses, unlocks, "
                    "manual grading, retakes); parents see the child/course grade context they were "
                    "invited to; students see their actionable coursework."
                ),
                _h2("Course lifecycle"),
                _ul(
                    [
                        "<strong>Developing / workspace drafts</strong> — build safely before students arrive",
                        "<strong>Active</strong> — day-to-day teaching",
                        "<strong>Closed</strong> — classroom taking pauses; historic grades remain meaningful",
                        "<strong>Trash / restore</strong> — soft-delete with restore paths when mistakes happen",
                    ]
                ),
                _p(
                    "Moving a course from Workspace into the Courses folder sets it closed so you "
                    "reactivate deliberately from the Courses page when ready."
                ),
                _faq(
                    [
                        (
                            "Can a co-teacher invite students?",
                            "Course management permissions follow who can manage the course. "
                            "Coordinate with the owner on invites and credits.",
                        ),
                        (
                            "Do copied courses copy the roster?",
                            "Course copies are content-focused: they do not bring along the previous "
                            "class roster. Only the appropriate owner enrollment is established for the copy.",
                        ),
                    ]
                ),
            ]
        ),
    },
]


def iter_article_specs():
    """Yield dicts with title, tags (list[str]), body (html str)."""
    for spec in ARTICLE_SPECS:
        tags = list(dict.fromkeys(spec["tags"]))  # stable unique
        yield {
            "title": spec["title"],
            "tags": tags,
            "body": spec["body"],
        }
