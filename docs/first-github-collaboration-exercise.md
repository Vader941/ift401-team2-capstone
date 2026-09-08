# First GitHub Collaboration Exercise

This beginner exercise teaches the workflow Team 2 will use for the capstone. It is intentionally small and requires no programming.

## What You Will Practice

- Clone the team repository
- Create a task branch
- Add and commit one file
- Push the branch
- Open a pull request
- Review another teammate's work
- Merge approved work
- Synchronize your local copy

## Before You Start

Install [GitHub Desktop](https://desktop.github.com/) and a text editor such as Visual Studio Code. Sign into GitHub Desktop and accept Nathan's repository invitation.

> [!IMPORTANT]
> This repository is public. Never add passwords, tokens, student ID numbers, private course materials, real financial information, or other sensitive information.

## Part 1: Clone the Repository

Cloning creates a working copy on your computer.

1. Open [Vader941/ift401-team2-capstone](https://github.com/Vader941/ift401-team2-capstone).
2. Select the green **Code** button.
3. Select **Open with GitHub Desktop**.
4. Choose a folder you can easily find and select **Clone**.
5. Confirm GitHub Desktop shows **Current branch: main**.
6. Select **Fetch origin** to check for updates.

Do not edit files while on `main`.

## Part 2: Create Your Branch

A branch keeps unfinished work separate from the team's approved version.

1. In GitHub Desktop, select **Current branch**.
2. Select **New branch**.
3. Name it using your GitHub username:

   ```text
   practice/your-github-username
   ```

4. Make sure it is based on `main`.
5. Select **Create branch**.
6. Confirm your new practice branch is displayed.

## Part 3: Add Your Practice File

Each teammate creates a different file, avoiding merge conflicts.

1. In GitHub Desktop, select **Repository > Open in Visual Studio Code**.
2. Open the `practice` folder.
3. Create `your-github-username.md`. For example, user `example-user` creates `practice/example-user.md`.
4. Add this content with your own answers:

   ```markdown
   # GitHub Practice: Your Name

   - GitHub username: your-github-username
   - Team role or area of interest: your answer
   - One thing I want to practice during this project: your answer
   ```

5. Save the file.
6. Return to GitHub Desktop.
7. Confirm that only your new file appears under **Changes**.

If unexpected files appear, stop and ask in Discord before committing.

## Part 4: Commit and Push

A commit records a checkpoint. Pushing sends the branch to GitHub.

1. Enter this commit summary in GitHub Desktop:

   ```text
   docs: add GitHub practice file
   ```

2. Select **Commit to practice/your-github-username**.
3. Select **Publish branch**.
4. Wait for the upload to finish.

Your work is on GitHub but is not yet part of `main`.

## Part 5: Open a Pull Request

1. Select **Create Pull Request** in GitHub Desktop.
2. In the browser, confirm:
   - Base branch: `main`
   - Compare branch: your practice branch
3. Use this title:

   ```text
   docs: add [username] practice file
   ```

4. Complete the pull-request template.
5. Under testing, state that you opened the Markdown file and verified its contents.
6. Select **Create pull request**.
7. Post the pull-request link in Discord and ask a teammate to review it.

Do not merge before receiving the required approval.

## Part 6: Review a Teammate's Pull Request

Review at least one pull request you did not create.

1. Open the link your teammate posted.
2. Read the **Conversation** tab.
3. Open **Files changed**.
4. Confirm:
   - Only the expected practice file was added.
   - The filename matches the contributor's GitHub username.
   - It contains no sensitive or unrelated information.
   - The Markdown is readable.
5. Select **Review changes**.
6. Choose:
   - **Approve** if ready.
   - **Request changes** if a correction is required.
   - **Comment** for a non-blocking question.
7. Explain your choice briefly and submit the review.

An approval means you actually checked the change.

## Part 7: Respond and Merge

If changes were requested:

1. Return to the same branch in GitHub Desktop.
2. Correct and save the file.
3. Commit and push the correction.
4. Reply to the review comment.
5. Ask the reviewer to check again.

After approval:

1. Open your pull request.
2. Confirm GitHub says it can be merged.
3. Select **Squash and merge**.
4. Review the final commit message.
5. Select **Confirm squash and merge**.
6. Delete the remote branch when GitHub offers.

## Part 8: Synchronize Your Computer

1. Switch to `main` in GitHub Desktop.
2. Select **Fetch origin**.
3. Select **Pull origin** if it appears.
4. Confirm the merged practice file now exists locally.
5. Delete your local practice branch after confirming the merge.

For future tasks, always update `main`, then create a new branch. Do not reuse an old task branch.

## Completion Checklist

- [ ] I cloned the repository.
- [ ] I created a practice branch from current `main`.
- [ ] I added only my practice file.
- [ ] I committed and pushed the branch.
- [ ] I opened a pull request.
- [ ] A teammate reviewed and approved it.
- [ ] I squash-merged it.
- [ ] I reviewed at least one teammate's pull request.
- [ ] I updated my local `main`.
- [ ] All three practice files appear in the repository.

## Common Problems

### I cannot push

Confirm you accepted the collaborator invitation and GitHub Desktop is signed into the correct account.

### GitHub will not let me merge

Check for a missing approval, unresolved conversation, or outdated branch.

### My branch is behind `main`

Use **Update branch** on the pull request if available. Ask in Discord if you are uncertain.

### I accidentally edited `main`

Do not push, discard, or overwrite anything blindly. Stop and ask for help. The work can usually be moved safely to a branch.

### I see a merge conflict

Do not guess which version should win or force-push. Post a screenshot in Discord so the affected teammates can resolve it together.

## Safety Rule

When uncertain, pause before force-pushing, deleting a branch, resolving a conflict, or discarding changes. Asking in Discord is easier than reconstructing overwritten work.
