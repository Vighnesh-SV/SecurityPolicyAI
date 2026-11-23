# Nebulon Synthetic Enterprise Phishing Email Dataset

## Overview

This release provides a publicly shareable synthetic enterprise phishing email dataset designed to support both behavioral phishing research and machine-learning benchmarking. The dataset is built around a fictitious organization, **Nebulon**, and includes enterprise-relevant workplace communication themes, matched legitimate and phishing emails, structured phishing-cue annotations, and de-identified human-subject response data.

The public release is based on the **final retained 146-email set** used for analysis and benchmarking. Although the broader human evaluation study included a larger candidate set, the files in this release correspond to the retained set used in reported analyses.

The release is intended to support research on phishing detection, human susceptibility, email realism, explainability, and benchmark development in enterprise-like settings.

## Version

- Version: `v1.0`
- Release date: `September 1, 2026`

## License

This dataset is released under the **Creative Commons Attribution-ShareAlike 4.0 International (CC BY-SA 4.0)** license.

## Files Included

### 1. `seed_dataset.csv`
The initial synthetic seed dataset used as a structured starting point during generation of the larger email corpus.

Includes:
- email content and metadata
- ground-truth phishing/legitimate labels
- binary phishing-cue indicators
- total signal counts

Unit of observation:
- one row per seed email

### 2. `final_email_dataset.csv`
The main released email corpus. This file contains the **final retained 146-email set** used for analysis and benchmarking.

Includes:
- unique email identifier (`email_id`)
- enterprise theme
- email metadata (`date`, `sender`, `recipient`, `subject`, `body`)
- ground-truth label (`true_label`)
- binary phishing-cue indicators
- total signal count

Unit of observation:
- one row per retained email

### 3. `email_level_human_summary.csv`
An email-level summary file containing aggregate participant response measures for each email in the **retained 146-email set**.

Includes:
- email identifier (`email_id`)
- core email metadata and annotations
- number of participant responses
- mean participant accuracy
- mean and standard deviation of confidence
- proportion and count of phishing vs. legitimate classifications

Unit of observation:
- one row per retained email

### 4. `participant_responses_anonymized.csv`
De-identified participant-level response data from the human evaluation study for the **retained 146-email set**.

Includes:
- anonymous participant identifier (`participant_id`)
- email identifier (`email_id`)
- participant classification
- participant confidence
- email metadata and annotations
- trial-level accuracy

Unit of observation:
- one row per participant-email response

### 5. `data_dictionary.xlsx`
Workbook documenting the variables included in each released file.

Tabs include:
- overview
- seed dataset
- final email dataset
- email-level human summary
- participant responses
- combined variable list

## File Relationships

The released files are linked through shared identifiers.

- `email_id` identifies a unique email and is used to link:
  - `final_email_dataset.csv`
  - `email_level_human_summary.csv`
  - `participant_responses_anonymized.csv`

- `participant_id` identifies an anonymized participant in:
  - `participant_responses_anonymized.csv`

Relationship summary:
- `final_email_dataset.csv`: one row per retained email
- `email_level_human_summary.csv`: one row per retained email
- `participant_responses_anonymized.csv`: multiple rows per email, one for each participant response
- `seed_dataset.csv`: one row per seed email

## Labels and Annotations

### Email labels
- `phish` = phishing email
- `legit` = legitimate email

### Binary phishing-cue indicators
The dataset includes six binary phishing-related cue annotations:

- `has_link`
- `has_attachment`
- `has_generic_greeting`
- `has_urgent_language`
- `has_external_sender`
- `has_request_personal_information`

These cues were used as interpretable annotations during dataset construction and analysis. They were not intended to function as simple deterministic markers of phishing.

### Total signal count
- `total_signals` = sum of the six annotated phishing-cue indicators for the email

## Data Conventions

Unless otherwise noted in the data dictionary:

- binary cue variables are encoded as `0/1`
- `true_label` is encoded as `phish` or `legit`
- participant classification variables use phishing/legitimate class labels as defined in the corresponding file
- confidence values are recorded on a `0-100` scale
- identifiers are synthetic or anonymized and do not correspond to real organizational identities

Users should consult `data_dictionary.xlsx` for variable-level definitions and coding details.

## Important Notes

- All emails are **synthetic**.
- All content is tied to the fictitious organization **Nebulon**.
- The dataset is intended for **research and benchmarking** purposes.
- Participant identifiers have been anonymized; original Prolific IDs are not included.
- Because the dataset was designed for public release, it does not contain real organizational communications or operationally sensitive information.
- Although the broader study involved a larger candidate set, the public release contains the **final retained 146-email set** used for analysis.

## Recommended Use

- Use `final_email_dataset.csv` for the main released email corpus.
- Use `email_level_human_summary.csv` for item-level behavioral summary analyses.
- Use `participant_responses_anonymized.csv` for participant-level behavioral analyses.
- Use `seed_dataset.csv` to inspect the structured starting point used during generation.
- Use `data_dictionary.xlsx` for variable definitions.

## Limitations

Users should interpret the data in light of the limitations described in the accompanying manuscript, including:

- the synthetic nature of the emails
- the simplified human-evaluation context
- the fact that the dataset is intended as a research and benchmarking resource rather than a substitute for naturally occurring enterprise email corpora

## Citation

If you use this dataset, please cite the dataset release and the accompanying manuscript when available.

Winokur, E. J., Treiman, L. S., Moore, A. G., Schutte, P., Ingram, J., & Sanchez, D. N. (2026). *Nebulon Enterprise Simulated Threats for Phishing Research (NEST-Phish): A synthetic enterprise phishing email dataset for behavioral and machine-learning research*. arXiv. https://arxiv.org/abs/2609.04474

## Contact / Notes

This dataset was developed as a synthetic, publicly shareable resource for phishing research. The accompanying manuscript is cited above but is not included as part of the dataset release package.