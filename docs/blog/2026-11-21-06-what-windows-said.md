# What Windows said: a first run on three operating systems

Until this week Tessri's suite ran on Linux and nowhere else. The tool claims to run anywhere Python 3.11 runs, so the claim was due a test. We added Windows and macOS to the matrix, pushed, and read what came back: macOS said nothing, and Windows failed eleven of 615 tests. Two of the eleven were real. This is the list, the two fixes, and what the other nine taught us about writing a suite that means the same thing on every system.

## Before the run: the encoding we knew about

One Windows failure was fixed before the first run, because it was easy to predict. Tessri's pages hold arrows, middle dots and the cycle sign (`→`, `·`, `⇄`), and file paths in any script. A console on Windows writes UTF-8, but a pipe or a file there takes the legacy code page, which has none of those characters, and Python stops at the first one with an encoding error. The command line now reconfigures its output streams to UTF-8 unless they already are; a test runs a command into a stream opened as cp1252 and reads the cycle sign back as UTF-8.

## The first run

Eleven of 615 tests failed on `windows-latest` with Python 3.12. By cause:

| Cause | Tests | Whose fault |
|---|---:|---|
| CRLF line endings in fixtures written through newline translation | 4 | the suite |
| File names Windows forbids (`"`, `<`, `>`) | 3 | the suite |
| An Astro file with CRLF line endings loses its frontmatter | 1 | the code |
| A file standing where a directory is needed | 1 | the code |
| Node's output read through the console's code page | 1 | the suite |
| POSIX mode bits asserted | 1 | the suite |

## The two that were the code's

**CRLF frontmatter.** The JavaScript analyzer reads the frontmatter of `.astro` files, the block between two `---` lines, for its imports. The pattern that found the block wanted a bare newline after the opening fence. An Astro file saved with CRLF line endings, which is what a Windows editor produces by default, had no frontmatter as far as the analyzer could see, so the components it imported looked like files nothing reaches. The pattern takes either line ending now, and a test writes the file with CRLF and checks that the import resolves. The suite only found this because its fixtures were, by accident, written with CRLF on Windows; the bug would have reached any Windows user of an Astro project.

**A file where a directory should be.** `tessri integration install` refuses to write when a target path cannot be read, and it checks that before it writes anything, so that a conflict never leaves half an installation behind. On POSIX, reading `.agents/skills/tessri/SKILL.md` when `.agents` is a file raises *not a directory*, which the check caught. Windows reports the same situation as *the path does not exist*, which the check took to mean *nothing there yet*; the write then failed on `mkdir`, and the installer rolled back what it had already written. The result was correct, but the promise, an error before any write, was broken on one system. The read now walks up to the nearest existing ancestor and refuses when that is a file, on every system, with the same sentence.

## The nine that were the suite's

**Newline translation.** The suite builds its repositories from Python strings. It wrote them with `write_text`, which on Windows turns every `\n` into `\r\n`. Every test that compared bytes, and the installer's receipt, which hashes the bytes it wrote, then met content the test author never typed. The fixture writer passes `newline=""` now and writes what it is given; four tests passed on the next run with no other change.

**Names Windows forbids.** Three tests name files with a double quote or angle brackets, to check that such names cannot break the HTML report or the diff parser. Windows will not create those files. The tests skip there, and the skip says why; the behaviour they protect is Linux and macOS behaviour, and it is still tested there on every run.

**A code page in a subprocess.** One test runs the page's script under node and reads what it prints. `subprocess.run(..., text=True)` decodes that with the console's code page, so a path with an umlaut came back as mojibake. The test asks for UTF-8 now, which is what node writes.

**Mode bits.** One test checks that the installer keeps a file's permissions. Windows has no permission bits to keep; the check is POSIX's and skips elsewhere.

## The second and third runs

The second run failed four tests, all of them fixtures that still wrote text through translation in a different place: a settings file written in a test's own `setUp`, a workflow file restored by hand. The third run was green on all four runners.

## What we keep from it

A fixture must be bytes the author wrote, on every system, or the test means different things in different places. An error for one condition can arrive under different names on different systems, and a check that matches one name has only been tested on one. A test that cannot run somewhere should say so and why, where the skip is read, rather than pass vacuously or be deleted. And a claim like *runs anywhere* is worth one line in a matrix, because the first run on a new system found two bugs that no amount of reading would have.

The suite now runs on Ubuntu with both supported Pythons and on Windows and macOS with the newest, on every pull request. [Contributing](https://github.com/tianyi-zhang-02/tessri/blob/main/CONTRIBUTING.md) says what the code keeps; this is one of the things it keeps now.
