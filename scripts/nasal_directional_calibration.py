"""Calibrate the two requested nasal categories separately on dev only.

Partial coverage remains explicit: absence of a valid threshold for one
direction never forces a grade, nor hides evidence available for the other.
Zero observed development errors is not a population reliability guarantee.
"""
import numpy as np

from fit_nasal_context_probe import policy_observations
from train_nasal_feature_probe import summarize


def directional_observations(rows, scores, review, matching):
    values = np.asarray(scores)
    if values.shape != (len(rows), 3) or not np.isfinite(values).all():
        raise ValueError('Invalid directional score matrix')
    result = []
    for row, score in zip(rows, values):
        group = row['expected_label']
        result.extend(policy_observations([row], score[None], review.get(group), matching.get(group)))
    return result


def select_directional_feedback(rows, scores):
    if not rows or any(r['split'] != 'dev' for r in rows):
        raise ValueError('Directional calibration requires development rows only')
    values = np.asarray(scores)
    if values.shape != (len(rows), 3) or not np.isfinite(values).all():
        raise ValueError('Invalid directional development scores')
    review = {}; matching = {}; summaries = {}
    for group in ('front', 'back'):
        positions = [i for i, r in enumerate(rows) if r['expected_label'] == group]
        subset = [rows[i] for i in positions]; subset_scores = values[positions]
        if not subset:
            review[group] = matching[group] = None
            summaries[group] = {'reason': 'no_development_targets'}
            continue
        ordered = np.sort(subset_scores, axis=1); gaps = ordered[:, -1]-ordered[:, -2]
        margins = sorted({0., *(float(np.nextafter(v, np.inf)) for v in gaps)})
        normal_count = sum(r['actual_label'] == group for r in subset)
        negative = []; positive = []
        for threshold in margins:
            negative.append({'margin': threshold, **summarize(policy_observations(subset, subset_scores, threshold, None))})
            positive.append({'margin': threshold, **summarize(policy_observations(subset, subset_scores, None, threshold))})
        eligible = [r for r in negative if normal_count >= 20 and r['false_nasal_accusations'] == 0 and r['correct_error_directions'] >= 2]
        chosen_r = max(eligible, key=lambda r: (r['correct_error_directions'], -r['margin'])) if eligible else None
        eligible = [r for r in positive if r['false_reassurances'] == 0 and r['correct_nasal_matches'] >= 5]
        chosen_m = max(eligible, key=lambda r: (r['correct_nasal_matches'], -r['margin'])) if eligible else None
        review[group] = chosen_r['margin'] if chosen_r else None
        matching[group] = chosen_m['margin'] if chosen_m else None
        summaries[group] = {'selected_review': chosen_r, 'selected_matching': chosen_m,
                            'available_normal_controls': normal_count}
    return review, matching, summaries
