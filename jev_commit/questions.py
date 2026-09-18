"""The five nouls, pinned to jev-1.13.0.

One judgment each, criteria written as situations rather than degrees, and an explicit
false side so the model has somewhere to land. Question 1 is a gate, not a finding: below
0.5 the mismatch finding is suppressed, which is what keeps `wip` out of the false alarms
(pi-warden src/done.ts:98-120 uses the same shape for verification_applies).
"""

MODEL = "jev-1.13.0"

MESSAGE_IS_SUBSTANTIVE = "message_is_substantive"
MESSAGE_MATCHES_DIFF = "message_matches_diff"
DEBUG_LEFTOVERS = "debug_leftovers"
SCOPE_CREEP = "scope_creep"
SECRET_SHAPED = "secret_shaped"

QUESTIONS = {
    MESSAGE_IS_SUBSTANTIVE: {
        "type": "noul",
        "instructions": {
            "question": "Does `message` make at least one checkable claim about what changed?",
            "focus": "Judge `message` alone. Ignore `hunks` and `files` for this question.",
        },
        "criteria": {
            "true": "The message states something about the change that could be checked against a diff, "
            "such as naming what was fixed, added, removed or renamed.",
            "false": "A placeholder or a bare label: wip, fix, update, stuff, a single word with no object, "
            "or a message that names no change at all.",
        },
    },
    MESSAGE_MATCHES_DIFF: {
        "type": "noul",
        "instructions": {
            "question": "Considering the claims in `message` about files that appear in `hunks`, "
            "is each of those claims visible there?",
            "focus": "Only claims about files present in `hunks`, plus any file `message` names by path. "
            "Claims about files that are not in `hunks` and not named in `message` are out of scope "
            "and do not make this false.",
        },
        "criteria": {
            "true": "Every such claim can be pointed at in these hunks, and any file the message names by "
            "path appears in `files`. A chunk that contains no claimed file is true.",
            "false": "A claim about a file that is in `hunks` is not supported by those hunks, or the message "
            "names a file by path that does not appear in `files`.",
        },
    },
    DEBUG_LEFTOVERS: {
        "type": "noul",
        "instructions": {
            "question": "Do the added lines in `hunks` include code whose only purpose was temporary "
            "debugging or local development?",
            "focus": "Added lines only, the ones beginning with +.",
        },
        "criteria": {
            "true": "A print or log statement added to trace execution, a commented-out block where working "
            "code used to be, a hardcoded localhost endpoint or an authentication bypass, a test "
            "disabled or skipped, or a TODO saying to remove the line.",
            "false": "Logging written in the style the surrounding code already uses, or code inside a module "
            "whose job is debugging, examples, or development tooling.",
        },
    },
    SCOPE_CREEP: {
        "type": "noul",
        "instructions": {
            "question": "Does this diff do work that `message` neither names nor implies?",
            "focus": "Judge whether each path belongs to the work the message describes. "
            "Do not judge how large the diff is.",
        },
        "criteria": {
            "true": "A path in `files` belongs to a part of the project the message never mentions and is not "
            "a mechanical consequence of what it does name, or the change the diff spends the most "
            "lines on is one the message never names.",
            "false": "Every path is either named by the message or follows mechanically from it: imports, "
            "call sites of a rename, lockfiles, generated files, and the tests for the changed code.",
        },
    },
    SECRET_SHAPED: {
        "type": "noul",
        "instructions": {
            "question": "Do the added lines in `hunks` write out a real credential that someone reading them "
            "could use to gain access?",
            "credential_types": [
                "API key or access token",
                "password or passphrase",
                "private key",
                "a URL, header or config entry that embeds one of these",
            ],
            "focus": "Judge the values actually written on added lines. Use the file path as context only.",
        },
        "criteria": {
            "true": "A complete credential value is written out and looks issued or chosen for real use, "
            "including values that are only base64 encoded.",
            "false": "No usable credential value is written out. Placeholder, example, dummy or test values, "
            "redacted or masked values, references to a secret stored elsewhere such as an "
            "environment variable or a password manager, encrypted values, public keys, hashes, "
            "checksums and commit SHAs are not credentials.",
        },
    },
}

# High means a finding for these, high means healthy for message_matches_diff.
FINDINGS = (DEBUG_LEFTOVERS, SCOPE_CREEP, SECRET_SHAPED)

# Labels name the risk, not the question, so a long bar always means a problem. The two
# healthy-high questions are printed as their complement (1 - noul) to match.
LABELS = {
    MESSAGE_IS_SUBSTANTIVE: "message is filler",
    MESSAGE_MATCHES_DIFF: "contradicts the diff",
    DEBUG_LEFTOVERS: "debug leftovers",
    SCOPE_CREEP: "unmentioned work",
    SECRET_SHAPED: "secret shaped",
}
