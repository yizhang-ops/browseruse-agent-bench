# Multilingual Task Proposal Examples

Use these examples when proposing new LexBench-Browser tasks. A good task describes what the
agent should do, what evidence proves success, and which browser-agent failure mode the task is
meant to test.

## Chinese Website Example

Target website: `www.xiaohongshu.com`

Language/region: Chinese, mainland China

User goal:

```text
在小红书搜索「杭州周末徒步」，找到一篇近期收藏数较高的笔记，返回标题、作者和路线名称。
```

Expected final state:

The agent has searched the site, opened a relevant note, and returned the note title, author, and
route name. If the site requires login or blocks the content, the agent should report that
limitation instead of inventing details.

Login requirement: no-login preferred; mark `login_required: true` only if the workflow cannot be
completed from public pages.

Evaluation criteria:

- searches with the intended Chinese query
- opens a relevant note instead of only reading search snippets
- extracts title, author, and route name from the page
- distinguishes route name from unrelated location tags
- reports login or anti-bot blocks when they occur

Failure mode being tested:

- Chinese rendering and input handling
- login popup interference
- dynamic card grids and lazy-loaded content
- distinguishing user-generated content from ads or recommendations

Suggested metadata:

```json
{
  "language": "zh",
  "website_region": "zh",
  "domain": "social_lifestyle",
  "reasoning_type": "multi_step",
  "robustness_tags": ["chinese_rendering", "login_popup", "lazy_load_scroll", "data_extraction"]
}
```

## English Website Example

Target website: `www.amazon.com`

Language/region: English, global or US

User goal:

```text
Search for "portable monitor", filter for 4-star-and-up products under $150, and return three
products with their names, prices, and ratings.
```

Expected final state:

The agent has applied the search, price, and rating filters, then returned three visible products
with names, prices, and average ratings. If Amazon redirects to a regional site, the agent should
note the currency or region.

Login requirement: no login.

Evaluation criteria:

- searches for the correct product category
- applies the price constraint
- applies or verifies the rating constraint
- extracts three products from filtered results
- includes product name, price, and rating
- notes regional redirect or currency differences when applicable

Failure mode being tested:

- filter and sort interactions
- cookie consent or delivery-location prompts
- regional redirects and currency differences
- noisy sponsored results

Suggested metadata:

```json
{
  "language": "en",
  "website_region": "en",
  "domain": "ecommerce",
  "reasoning_type": "multi_step",
  "robustness_tags": ["cookie_consent", "filter_sort", "data_extraction", "ad_overlay"]
}
```

## Cross-Language Example

Target website: `www.tripadvisor.com` or another travel site with multilingual listings

Language/region: English query, mixed-language content

User goal:

```text
Find a highly rated ramen restaurant near Shinjuku Station that is open on Sunday, then return
the English name, Japanese name if shown, rating, and address.
```

Expected final state:

The agent returns a relevant restaurant near Shinjuku Station with rating, address, Sunday opening
status, and both names when available.

Login requirement: no login.

Evaluation criteria:

- uses a travel or maps site suitable for restaurant lookup
- constrains the search to Shinjuku Station
- verifies Sunday opening status
- extracts rating and address
- preserves Japanese text when visible
- does not confuse ads, nearby neighborhoods, or unrelated chain locations

Failure mode being tested:

- cross-language entity matching
- map/list result navigation
- opening-hours extraction
- dynamic content and partial localization

Suggested metadata:

```json
{
  "language": "en",
  "website_region": "global",
  "domain": "social_lifestyle",
  "reasoning_type": "deep_analysis",
  "robustness_tags": ["cross_language", "filter_sort", "data_extraction", "realtime_data"]
}
```

## Proposal Checklist

- The user goal is realistic and not overfit to a single DOM layout.
- The target website can be accessed by reviewers in the intended region.
- The expected final state is observable from public pages or clearly marks login needs.
- Evaluation criteria include both success evidence and common mistakes.
- Robustness tags explain what the task adds to the benchmark.
- Safety, purchase, account, or personal-data risks are disclosed.
