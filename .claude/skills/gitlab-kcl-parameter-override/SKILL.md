---
name: gitlab-kcl-parameter-override
description: Use when a user wants Claude to trigger GitLab KCL artifact generation for a repo and part path with temporary parameters.kcl overrides, without editing or committing KCL.
---

# GitLab KCL Parameter Override

## Overview

Use this skill to generate `kcl-artifacts` for a part by triggering a target
GitLab pipeline with pipeline inputs. This is for temporary parameter sweeps and
preview artifacts. Do not edit `parameters.kcl`, `main.kcl`, or commit changes
unless the user explicitly asks for persistent source changes.

The target repo must expose pipeline-level inputs and forward them into the
`kcl-artifacts` component:

```yaml
spec:
  inputs:
    kcl_main_kcl_paths:
      type: string
      default: "[]"
    kcl_parameters_json:
      type: string
      default: "{}"
---

include:
  - component: $CI_SERVER_FQDN/my-group/gitlab-kcl-actions/kcl-artifacts@1.0.0
    inputs:
      main_kcl_paths: '$[[ inputs.kcl_main_kcl_paths ]]'
      parameters_json: '$[[ inputs.kcl_parameters_json ]]'
```

GitLab pipeline inputs are the right contract here because they are evaluated
and validated when the pipeline is created. Use inputs, not ad hoc CI variables,
for user-provided part parameters.

## Required Inputs

- GitLab project ID or path, such as `123456` or `my-group/my-part-repo`.
- Git ref, usually `main`.
- Repo-relative part path. Accepted forms:
  - `path/to/main.kcl`
  - `path/to/parameters.kcl`, normalized to `path/to/main.kcl`
  - `path/to/assembly-dir/`, normalized to `path/to/assembly-dir/main.kcl`
- Parameter overrides as a JSON object or `name=value` pairs.
- Trigger token, usually from `GITLAB_TRIGGER_TOKEN`.

## Workflow

1. Normalize the part path to a repo-relative `main.kcl`.
   - Reject absolute paths.
   - Reject `..` traversal.
   - If the user gives an arbitrary imported file, inspect the repo to find the
     owning assembly's `main.kcl`. If you cannot prove the owner, ask for the
     assembly `main.kcl` path.
2. Build compact JSON for the parameter overrides.
   - Keep numbers and booleans typed, for example `{"width":24,"enabled":true}`.
   - Do not quote numbers just to make shell quoting easier. That is how sadness
     gets serialized.
   - Keep the JSON small. GitLab input strings have size limits, so this is for
     sweep-style overrides, not shoving a database through a straw.
3. Trigger the pipeline with inputs:
   - `kcl_main_kcl_paths` as a JSON array of `main.kcl` paths.
   - `kcl_parameters_json` as the compact JSON object.
4. Report the created pipeline URL and remind the user that artifacts will be in
   the `kcl-artifacts` job artifacts.

## Helper Script

Prefer the helper script so path normalization, JSON typing, and GitLab form
fields stay consistent:

```sh
python .claude/skills/gitlab-kcl-parameter-override/scripts/trigger_kcl_artifacts.py \
  --gitlab-host https://gitlab.example.com \
  --project my-group/my-part-repo \
  --ref main \
  --part-path parts/widget/parameters.kcl \
  --parameter width=24 \
  --parameter depth=6 \
  --execute
```

The helper defaults to a dry run. Add `--execute` only after the target project,
ref, path, and parameters are clearly correct.

You can also pass a JSON object directly:

```sh
python .claude/skills/gitlab-kcl-parameter-override/scripts/trigger_kcl_artifacts.py \
  --project 123456 \
  --part-path parts/widget/main.kcl \
  --parameters-json '{"width":24,"depth":6}' \
  --execute
```

## Manual API Shape

If you cannot use the helper, send this shape to the GitLab pipeline trigger
API:

```sh
curl --fail --request POST \
  --form "token=$GITLAB_TRIGGER_TOKEN" \
  --form "ref=main" \
  --form 'inputs[kcl_main_kcl_paths]=["parts/widget/main.kcl"]' \
  --form 'inputs[kcl_parameters_json]={"width":24,"depth":6}' \
  "https://gitlab.example.com/api/v4/projects/my-group%2Fmy-part-repo/trigger/pipeline"
```

## Guardrails

- Do not use CI variables for these parameter values unless the target repo has
  not adopted pipeline inputs yet and the user accepts the weaker contract.
- Do not send secrets in `kcl_parameters_json`; these values are modeling
  parameters and may be visible in pipeline metadata or logs.
- Do not trigger broad repo-wide artifact generation when the user named a
  single part. Always pass `kcl_main_kcl_paths` for targeted runs.
- If GitLab rejects an input, fix the target repo's `spec:inputs` or the sent
  value. Do not bypass validation by moving the value into a variable.
