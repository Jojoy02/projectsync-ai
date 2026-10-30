# ProjectSync AI data model

- **Work fact**: one evidenced event/result. May reference a business and a project, but is counted once.
- **Business/product**: the user's ongoing functional area; it can contain routine work not tied to a formal project.
- **Project**: a goal with milestones/deliverables; it can span multiple business areas.
- **Contribution**: `completed`, `coordinated`, `followed_up`, or `background`.
- **Evidence**: source URI, title, date, excerpt, revision/updated time and confidence.
- **Draft**: `daily` or `weekly`, period, text, version and confirmation status.
- **Target mapping**: explicit document and block owned by the current user. A shared document is not permission to update other people's blocks.

The local CLI database defaults to `~/.projectsync/projectsync.sqlite3`; it is deliberately outside the repository so private work facts are not accidentally committed to Git.
