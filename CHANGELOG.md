# Changelog

## [1.2.0](https://github.com/viktor-haag/ramen/compare/v1.1.0...v1.2.0) (2026-10-26)


### Features

* **cover-letters:** API, attachments, reset and version flag ([5d78e87](https://github.com/viktor-haag/ramen/commit/5d78e871fdb6b011fc75c3b2ba9f5c76d5db7200))
* **cover-letters:** configurable LaTeX compile time limit (default 180 s) ([406cec4](https://github.com/viktor-haag/ramen/commit/406cec4341fde702740c5bd6cb24976593b41c44))
* **cover-letters:** context, prompts and answer parsing ([013c3fa](https://github.com/viktor-haag/ramen/commit/013c3fa83f5a352da7d7f14ca37fa9ab94be34bb))
* **cover-letters:** data model, migration and default template ([c7284a7](https://github.com/viktor-haag/ramen/commit/c7284a7d8b5bc2e75efc2def90f18d8e712c8d3a))
* **cover-letters:** in-memory stream buffer for running jobs ([9c7ad40](https://github.com/viktor-haag/ramen/commit/9c7ad400b46450e8e309952132d75bc3e3876179))
* **cover-letters:** plain-text answer format with note marker ([7821d69](https://github.com/viktor-haag/ramen/commit/7821d696328c75ffd7ba387fcf50ff9f10f985ba))
* **cover-letters:** server-sent events for streaming drafts ([2d89b45](https://github.com/viktor-haag/ramen/commit/2d89b452e65c95795cd4773468fba088b692d231))
* **cover-letters:** state and background jobs ([df8261d](https://github.com/viktor-haag/ramen/commit/df8261ddc9f22396ae5ffb3026afe71202d4e0b1))
* **cover-letters:** template management API ([123a034](https://github.com/viktor-haag/ramen/commit/123a034f3a37e811c4fc46dc1ed54f54be91b7d1))
* **frontend:** cover letter editor view ([fbaca47](https://github.com/viktor-haag/ramen/commit/fbaca470b1860be32249d39ee3426e04870f93dc))
* **frontend:** cover letter section and create dialog ([dc0698a](https://github.com/viktor-haag/ramen/commit/dc0698a3919987d663ef92d27407d5f7c986e0a5))
* **frontend:** cover letter stores and error texts ([7b1a044](https://github.com/viktor-haag/ramen/commit/7b1a0446b780b8d66d9c40ebe6e79fc9d572a125))
* **frontend:** cover letter template management ([013d2a4](https://github.com/viktor-haag/ramen/commit/013d2a4cd1de9a5bf214b6f24e32177eb7332749))
* **frontend:** locked editor takes no clicks, cursor or focus ([45c276c](https://github.com/viktor-haag/ramen/commit/45c276c80d5b33298116eb5f12fffa0e0048a929))
* **frontend:** show streaming text in the locked editor ([516e1e9](https://github.com/viktor-haag/ramen/commit/516e1e99d0364065a209be4ad1d88dc5be9dcc9c))
* **frontend:** stream cover letter drafts via EventSource ([e763a86](https://github.com/viktor-haag/ramen/commit/e763a86b429539bc8d2a42de3eb9ce82b26ff836))
* **latex:** forbidden-command guard ([7d7c5ab](https://github.com/viktor-haag/ramen/commit/7d7c5abebafa92c999cdab4dfc39fa071278ac36))
* **latex:** tectonic compiler ([21f8336](https://github.com/viktor-haag/ramen/commit/21f833689059b15952e957442c268df220f6c32b))
* **llm:** stream through the runner ([c78c3ee](https://github.com/viktor-haag/ramen/commit/c78c3ee8e1862c4b85526a5375ac68f13a42f0e7))
* **llm:** streaming completions for all providers ([1351031](https://github.com/viktor-haag/ramen/commit/135103189a81f7aab330e9fb3b2cec8c21372411))
* **prompts:** cover letter prompt ([0affb13](https://github.com/viktor-haag/ramen/commit/0affb135375347992a1cc4ae73f15f0392516fa0))


### Bug Fixes

* **backend:** cover letter final review fixes ([b02fd4b](https://github.com/viktor-haag/ramen/commit/b02fd4b341ffba7ebd2671306838d6f40a30ddb1))
* **backend:** stream automatic repairs by setting status generating ([df879b4](https://github.com/viktor-haag/ramen/commit/df879b4214ee8e7718c6f647db587a56df0f9fc8))
* **build:** UTF-8 dash in README table, document TARGETARCH ([d510c83](https://github.com/viktor-haag/ramen/commit/d510c8348886411c438007dc9f609c548ce23422))
* **cover-letters:** guard job writes against reused ids, clear stale errors, unlink PDFs after commit ([2db9bd2](https://github.com/viktor-haag/ramen/commit/2db9bd2846e3856b8ac7aa54d7bb0ddc5263e12f))
* **cover-letters:** keep all templates on reset, test with real data ([e39feec](https://github.com/viktor-haag/ramen/commit/e39feecb981faa656410cb70f6d1a618c491dd0c))
* **cover-letters:** keep the streamed preview a prefix of the parsed letter ([4754fb3](https://github.com/viktor-haag/ramen/commit/4754fb32cad8cef6585ac48a6f882c776fb9b6c8))
* **frontend:** cover letter editor review fixes ([69613cb](https://github.com/viktor-haag/ramen/commit/69613cb86f72d5959605397f5c84b8ff0e05cab0))
* **frontend:** cover letter section status and dialog readiness ([e9a870c](https://github.com/viktor-haag/ramen/commit/e9a870c1eae31006f7a40cb54b4da585ad6bf6f7))
* **frontend:** cover letter template card review fixes ([750a05f](https://github.com/viktor-haag/ramen/commit/750a05f8f57f5b1423fe95217203700173c68d66))
* **frontend:** guard cover letter store against stale responses ([16ed5ab](https://github.com/viktor-haag/ramen/commit/16ed5ab511ae7e807abe5a21e9960a1510325c81))
* **frontend:** keep stream text until the final letter, no undo of streamed text ([fed1583](https://github.com/viktor-haag/ramen/commit/fed1583b94e2465d9f472dc3f869f69da9b596d0))
* **frontend:** offer the LLM repair for latex_forbidden too ([daae41b](https://github.com/viktor-haag/ramen/commit/daae41bdb2e8edf6e0ab7eba746b3e75177604ed))
* **frontend:** per-app stream give-up, drop dead token, close on 404 and browser give-up ([2078d9f](https://github.com/viktor-haag/ramen/commit/2078d9f76d7223c34a606818588c7ecce9389304))
* **frontend:** put German delete note on the template text, not search profiles ([5ae8536](https://github.com/viktor-haag/ramen/commit/5ae8536ceaa342c7118bde422c71925f938a7b5a))
* **latex:** check split \begin{env} across lines ([7973fdf](https://github.com/viktor-haag/ramen/commit/7973fdfca5ce2777c7858e730be30df1869562bc))
* **latex:** kill process tree on timeout, mask paths, chown cache, minimal env ([bbb3c0f](https://github.com/viktor-haag/ramen/commit/bbb3c0fb5f3d4ebbb92cae9d11780bbdda3cddfe))
* **latex:** switch guard to allowlist design ([94748a7](https://github.com/viktor-haag/ramen/commit/94748a72a10d4d03ea31f6df1dcde56b3f87cb5a))
* **llm:** map only 2xx status errors as mid-stream error events ([1867586](https://github.com/viktor-haag/ramen/commit/1867586378e321853954167b91fcf0db6fd934cc))

## [1.1.0](https://github.com/viktor-haag/ramen/compare/v1.0.0...v1.1.0) (2026-10-26)


### Features

* **applications:** CSV and Excel export ([74dc3a2](https://github.com/viktor-haag/ramen/commit/74dc3a26651eb2146d379df3b183e4037d6393a3))
* **llm:** editable prompts with a locked format part ([fca337b](https://github.com/viktor-haag/ramen/commit/fca337b799f3ea116b6e0d140b8c4f3bf4c02e27))
* **llm:** usage and daily limits per LLM configuration ([ad4c698](https://github.com/viktor-haag/ramen/commit/ad4c698426ae1320cdb0008e6b85c2da694aca95))
* **plugins:** JobSpy job boards (LinkedIn, Indeed, Glassdoor, Google and more) ([a281836](https://github.com/viktor-haag/ramen/commit/a28183611d3791b0304b6368c27c1a16dc3902c8))
* **plugins:** opt-in plugins with a warning notice ([c00bc72](https://github.com/viktor-haag/ramen/commit/c00bc72185f988ee611d26ab4895dc2dd9e1da8f))
* **profiles:** several cities per search profile ([22489b3](https://github.com/viktor-haag/ramen/commit/22489b3a14ab5e9e32190b8945d2fb4b5703b366))
* **ui:** city chips in the search profile dialog ([bd4bdc1](https://github.com/viktor-haag/ramen/commit/bd4bdc18aa78e97718a2b05ba144d6b5074ec699))
* **ui:** export applications as CSV or Excel ([7b432be](https://github.com/viktor-haag/ramen/commit/7b432be5a4d1cf9458dfc170ea4ad5579a01bcf2))
* **ui:** per-config usage table and limit settings ([4b3c9ee](https://github.com/viktor-haag/ramen/commit/4b3c9eec9265e21fc43edd9ad3ad5e1b6f0df3df))
* **ui:** prompts card in the AI settings ([3fa9d44](https://github.com/viktor-haag/ramen/commit/3fa9d444034fe8c4a5d1bf164d786fba42de2291))


### Bug Fixes

* **applications:** cap export cells at Excel's limit ([471c9ee](https://github.com/viktor-haag/ramen/commit/471c9eeab52a6389ccda82fe1cda12b1a7744d68))
* **dashboard:** one chronological run list with a capped length ([be91d6f](https://github.com/viktor-haag/ramen/commit/be91d6ffad6c47cfe76b2253bd40cacb202e7d96))
* **plugins:** JobSpy hours filter, Google query, HTML descriptions and mapping hardening ([25929c1](https://github.com/viktor-haag/ramen/commit/25929c15772becb7eecf2034e64246f6a74b842c))
* **profiles:** keep a legacy location string as the single city ([b89c7ea](https://github.com/viktor-haag/ramen/commit/b89c7ea13f583bd62525a5f941d0bf248e434d82))
* **prompts:** trim prompt text before validating and storing ([fb10519](https://github.com/viktor-haag/ramen/commit/fb10519c77dc9ad1f6932b019379bec416956d97))
* **runner:** no run stays running after a broken pool or shutdown ([f553aa7](https://github.com/viktor-haag/ramen/commit/f553aa7a0137504876852a66affd4f2263807bb8))
* **runner:** readable plugin errors, pool recovery and spaced starts ([dd97060](https://github.com/viktor-haag/ramen/commit/dd97060df7f69a9932fef1861cc4f798f177723e))
* **settings:** guard missing per_config and clarify euro totals without prices ([44860ba](https://github.com/viktor-haag/ramen/commit/44860ba14cf8ed855cd3e2729a969b21b3e45951))
* **ui:** limit prompt length, flush uncommitted profile chips on save, reset locale in afterEach ([76808bc](https://github.com/viktor-haag/ramen/commit/76808bc8ac8f57b60be3c25866cd7ac67327bc9c))
* **ui:** phone layout without horizontal overflow ([63f8c7f](https://github.com/viktor-haag/ramen/commit/63f8c7f30a641a84ee517e3c484af2a187b6a0f7))

## [1.0.0](https://github.com/viktor-haag/ramen/compare/v0.1.0...v1.0.0) (2026-10-25)


### Miscellaneous Chores

* release 1.0.0 ([7dcd5a9](https://github.com/viktor-haag/ramen/commit/7dcd5a9d74253eea0d2f1b8e9233c0a5fae8ae07))

## 0.1.0 (2026-10-25)


### Features

* :tada: initial commit ([b23542a](https://github.com/viktor-haag/ramen/commit/b23542aecf4efeed879f0e9a00905b6034e12de6))
* **ui:** update chip and About RAMEN card ([9e9609f](https://github.com/viktor-haag/ramen/commit/9e9609fd90c9bde9dc9b8a36c44e880956753af2))
* **updates:** version API, update_check setting and scheduled check ([768c9d7](https://github.com/viktor-haag/ramen/commit/768c9d70e544bb27dbde19cd66199050ad1497c3))
* **updates:** version source and GitHub release checker ([de14862](https://github.com/viktor-haag/ramen/commit/de148626e37d5b34841755b3a4fdccaa0a116d65))


### Bug Fixes

* **release:** start at 0.1.0 and keep version tests bump-proof ([95b4fbe](https://github.com/viktor-haag/ramen/commit/95b4fbe3f9e67d8869c9ebd21081d619ac97e943))
