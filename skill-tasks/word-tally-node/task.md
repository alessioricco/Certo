# Word tally

Build `tally`, a small command-line program in Node.js, run as
`node tally.js FILE...`. CommonJS, no TypeScript, and only Node's
built-in modules.

## What it does

- It reads the text files named on the command line, in the order
  given, as one text.
- A word is a run of the letters `a` to `z` and the digits `0` to `9`,
  after the text is turned to lower case. Every other character,
  accented letters included, separates words.
- It prints one line per different word: the count, one space, the
  word, such as `3 the`. The most frequent word comes first; words with
  the same count are in alphabetical order.
- Two options, which may come before or after the file names:
  - `--top N`: print only the first `N` lines;
  - `--min-length L`: leave out words shorter than `L` characters.

  `N` and `L` must be whole numbers of at least 1.
- Files with no words print nothing.
- Errors print one line starting with `tally: ` to standard error and
  nothing to standard output:
  - no file named, an unknown option, an option without its value, or a
    value that isn't allowed: exit code 2;
  - a file that can't be read: exit code 1.
- Otherwise the exit code is 0.

Also write tests for it with `node:test`.
