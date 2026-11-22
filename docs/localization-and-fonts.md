# Localization and font coverage

I worked on two kinds of localization. The server generated its own notices, and the client had existing dialogue and interface text. I tracked them separately because finishing the server catalog could still leave a player looking at untranslated menus or missing glyphs.

## What I built

- A shared registry for fourteen language options. It recorded locale aliases, number formatting, plural forms, writing direction, and review status.
- An offline catalog validator. It checked missing and stale keys, placeholder names, plural forms, duplicate JSON keys, Unicode normalization, and whether text appeared to be written in the expected script.
- Checks for problems that only show up with particular languages. Japanese needed a round trip through the expected encoding. Thai needed checks for misplaced marks and long runs without breaks. Arabic needed care around names and numbers inserted into right-to-left text.
- A coverage tool that reads character maps from TrueType and OpenType fonts and embedded SWF font tables. It let me compare the available glyphs with the characters a language needed before starting the client.

## What I found

The staged server catalogs passed the technical checks for 28 message keys across fourteen language options. Several translations were still machine drafts that needed native-speaker review. The text checks also caught a width issue that a character count alone would have missed. A line can fit its display budget and still exceed its UTF-8 byte budget.

The first font audit found that the interface fonts were missing every Korean syllable, Thai character, and Arabic character in the sets I checked. They also lacked 94 of the 141 Vietnamese tone-marked vowels I checked and the French no-break space. Different parts of the interface used different fonts, so a pass for menus could still leave gaps in nameplates or text panels.

I could measure available glyphs from the font files. Arabic shaping, Thai mark placement, and clipping in the actual interface still needed to be observed in the client. Those measurements and translation review were open when I paused.

The Python modules in this snapshot preserve the offline checks. The tests use sample strings and font tables generated for the tests.
