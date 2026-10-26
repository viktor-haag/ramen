# Changelog

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
