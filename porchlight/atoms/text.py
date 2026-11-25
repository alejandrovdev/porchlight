"""Text that comes from a session, made safe to print or to log.

A title, a prompt, a name or what a model wrote may hold control characters: a terminal
runs the escape sequences they start, and a carriage return writes over what was printed.
JSON also lets a transcript hold half a character (a lone surrogate), which no file and no
terminal can take.

    printable(text, keep="")   each control character (C0, DEL, C1) but those in `keep`
                               replaced by U+FFFD, each lone surrogate dropped; letters,
                               accents and emoji stay as they are
    one_line(text)             printable, on one line: each run of white space (line
                               breaks and tabs too) one space, none at either end
"""

import re

REPLACEMENT = "\ufffd"  # the replacement character, as decoders use it
CONTROLS = "".join(map(chr, range(0x20))) + "".join(map(chr, range(0x7F, 0xA0)))
SURROGATES = re.compile("[\ud800-\udfff]")
# The control characters Python counts as white space: one_line makes them spaces.
SPACES = "".join(character for character in CONTROLS if character.isspace())


def printable(text, keep=""):
    unsafe = "".join(character for character in CONTROLS if character not in keep)
    text = SURROGATES.sub("", str(text))
    return re.sub("[%s]" % re.escape(unsafe), REPLACEMENT, text)


def one_line(text):
    return " ".join(printable(text, keep=SPACES).split())
