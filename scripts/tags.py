"""The reasoning tags, built from characters so no source file or tool output ever contains the literal text.

Some agent tool renderers strip HTML-like tags from what they show, which makes a literal think tag
invisible and caused a long debugging loop. Import these constants in code and tests instead of typing the tags.
"""
THINK_OPEN = chr(60) + "think" + chr(62)
THINK_CLOSE = chr(60) + "/think" + chr(62)
