"""What is the day-90 model worth on students the day-7 rule has not already flagged?

The committed precision figures (0.722 GGG, 0.838 BBB) are measured over every
student with a journey. Some of those students are silent through day 7 and engage
later -- the zero-activity rule catches them for free, 83 days earlier, with no graph
analytics. If the model's skill is concentrated there, its marginal contribution is
smaller than what is committed.

So: same split, same seed, same features, but the holdout is partitioned into the
students the rule already flagged and the students it did not. The second group is
the honest denominator for the model.
"""

import os
import random
import sys
from datetime import timedelta
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / 'src' / '.env')
sys.path.insert(0, str(ROOT / 'src'))

from neo4j import GraphDatabase
from graphdatascience.session import (
    AuraAPICredentials, DbmsConnectionInfo, GdsSessions, SessionMemory)

MODULES = os.environ.get('MODULES', 'GGG,BBB').split(',')
CUTOFF = 90
RULE_DAY = 7
PASS_RESULTS = ['Pass', 'Distinction']
HOLDOUT_FRACTION = 0.30
SEED = 42
BATCH = 200

driver = GraphDatabase.driver(os.environ['NEO4J_URI'],
                              auth=(os.environ['NEO4J_USERNAME'],
                                    os.environ['NEO4J_PASSWORD']))
DB = os.getenv('NEO4J_DATABASE') or None


def run(query, **params):
    with driver.session(database=DB) as session:
        return session.run(query, **params).data()


BUILD = '''
UNWIND $studentIds AS studentId
MATCH (s:Student {id: studentId})-[r:REVIEWED_MATERIAL]->(m:EducationalMaterial)
      <-[:HAS_MATERIAL]-(c:Course)
WHERE c.codeModule = $module
WITH s, m, r ORDER BY r.date, m.id
WITH s, collect({material: m, day: r.date + $shift, clicks: r.sumClick,
                 typeId: $typeIds[m.activityType]}) AS events
UNWIND range(0, size(events) - 1) AS i
WITH s, i, events[i] AS event
WITH s, i, event.material AS material, event.day AS day,
     event.clicks AS clicks, event.typeId AS typeId
CREATE (ev:Interaction {module: $module, studentId: s.id, seq: i, day: day,
                        clicks: clicks, activityTypeId: typeId,
                        features: [log(toFloat(clicks) + 1.0)]})
CREATE (ev)-[:OF_MATERIAL]->(material)
WITH s, ev ORDER BY ev.seq
WITH s, collect(ev) AS chain
WITH s, chain, chain[0] AS firstEvent
CREATE (s)-[:FIRST_INTERACTION]->(firstEvent)
WITH chain
UNWIND range(0, size(chain) - 2) AS j
WITH chain[j] AS previous, chain[j + 1] AS following
CREATE (previous)-[:NEXT_INTERACTION]->(following)
RETURN count(*) AS links
'''

WINDOW = '''
MATCH (s:Student)-[:WAS_REGISTERED]->(:StudentRegistration)-[cc:CONTAINS_COURSE]->(c:Course)
WHERE c.codeModule = $module
WITH DISTINCT s, cc.finalResult AS finalResult
OPTIONAL MATCH (s)-[r:REVIEWED_MATERIAL]->(:EducationalMaterial)<-[:HAS_MATERIAL]-(c2:Course)
WHERE c2.codeModule = $module AND ($cutoff IS NULL OR r.date <= $cutoff)
WITH s, finalResult, coalesce(sum(r.sumClick), 0) AS clicks
SET s.passed = CASE WHEN finalResult IN $passResults THEN 1 ELSE 0 END,
    s.logClicks = log(toFloat(clicks) + 1.0)
'''

# The rule exactly as measured offline: still registered at RULE_DAY, and no
# material interaction on or before it. Both facts are observable on the day.
RULEFLAG = '''
MATCH (s:Student)-[:WAS_REGISTERED]->(:StudentRegistration)-[cc:CONTAINS_COURSE]->(c:Course)
WHERE c.codeModule = $module
// isNaN is load-bearing: pandas NaN arrives as a float NaN, not null. 22,521 of
// 32,593 dateUnregistration values are NaN and none are null, so an `IS NULL OR
// > day` test silently drops every student who never unregistered -- 49 flagged
// instead of 391 for GGG at day 14.
WITH s, max(CASE WHEN cc.dateUnregistration IS NULL
                   OR isNaN(cc.dateUnregistration)
                   OR cc.dateUnregistration > $ruleDay
                 THEN 1 ELSE 0 END) AS stillRegistered
OPTIONAL MATCH (s)-[r:REVIEWED_MATERIAL]->(:EducationalMaterial)<-[:HAS_MATERIAL]-(c2:Course)
WHERE c2.codeModule = $module AND r.date <= $ruleDay
WITH s, stillRegistered, count(r) AS earlyEvents
SET s.ruleFlagged = CASE WHEN stillRegistered = 1 AND earlyEvents = 0 THEN 1 ELSE 0 END
RETURN sum(s.ruleFlagged) AS flagged, count(*) AS students
'''

PROJECTION = '''
MATCH (src)-[r:FIRST_INTERACTION|NEXT_INTERACTION]->(tgt:Interaction)
WHERE tgt.module = $module AND tgt.day <= $maxDay
RETURN gds.graph.project.remote(src, tgt, {
    sourceNodeLabels: labels(src),
    targetNodeLabels: labels(tgt),
    sourceNodeProperties: src { .id, .day, .clicks, .activityTypeId, .features,
                                .passed, .logClicks, .ruleFlagged,
                                isHoldout: CASE WHEN src.id IN $holdout
                                                THEN 1 ELSE 0 END },
    targetNodeProperties: tgt { .day, .clicks, .activityTypeId, .features },
    relationshipType: type(r)
})
'''


def detection(frame):
    at_risk = int((frame.act == 0).sum())
    flagged = int((frame.pred == 0).sum())
    caught = int(((frame.act == 0) & (frame.pred == 0)).sum())
    return {'n': len(frame), 'at_risk': at_risk, 'flagged': flagged,
            'caught': caught,
            'recall': caught / at_risk if at_risk else 0.0,
            'precision': caught / flagged if flagged else 0.0,
            'accuracy': float((frame.pred == frame.act).mean()) if len(frame) else 0.0}


sessions = GdsSessions(api_credentials=AuraAPICredentials(
    os.environ['AURA_CLIENT_ID'], os.environ['AURA_CLIENT_SECRET'],
    os.environ['AURA_PROJECT_ID']))
gds = None
records = []
try:
    gds = sessions.get_or_create(
        session_name=f"oulad-marginal-{os.environ['AURA_CLIENT_ID'][:8]}",
        memory=SessionMemory.m_16GB,
        db_connection=DbmsConnectionInfo(
            aura_instance_id=os.environ['AURA_INSTANCEID'],
            username=os.environ['NEO4J_USERNAME'],
            password=os.environ['NEO4J_PASSWORD'], database=DB),
        ttl=timedelta(hours=3))
    print('session ready\n', flush=True)

    for MODULE in MODULES:
        print('=' * 78)
        print(f'MODULE {MODULE}')
        print('=' * 78, flush=True)

        span = run('''
        MATCH (s:Student)-[r:REVIEWED_MATERIAL]->(m:EducationalMaterial)
              <-[:HAS_MATERIAL]-(c:Course)
        WHERE c.codeModule = $module
        RETURN min(r.date) AS minDate, max(r.date) AS maxDate, count(r) AS events
        ''', module=MODULE)[0]
        SHIFT = -min(0, span['minDate'])
        print(f"  {span['events']:,} events, days {span['minDate']}..{span['maxDate']}",
              flush=True)

        TYPE_IDS = {r['activityType']: i for i, r in enumerate(run('''
        MATCH (m:EducationalMaterial)<-[:HAS_MATERIAL]-(c:Course)
        WHERE c.codeModule = $module
        RETURN DISTINCT m.activityType AS activityType ORDER BY activityType
        ''', module=MODULE))}

        pending = [r['studentId'] for r in run('''
        MATCH (s:Student)-[:REVIEWED_MATERIAL]->(:EducationalMaterial)
              <-[:HAS_MATERIAL]-(c:Course)
        WHERE c.codeModule = $module AND NOT (s)-[:FIRST_INTERACTION]->(:Interaction)
        RETURN DISTINCT s.id AS studentId ORDER BY studentId
        ''', module=MODULE)]
        if pending:
            print(f'  building the chain for {len(pending):,} students', flush=True)
            for start in range(0, len(pending), BATCH):
                run(BUILD, studentIds=pending[start:start + BATCH], module=MODULE,
                    shift=SHIFT, typeIds=TYPE_IDS)
            print('  chain built', flush=True)

        run(WINDOW, module=MODULE, cutoff=CUTOFF, passResults=PASS_RESULTS)
        flag_stats = run(RULEFLAG, module=MODULE, ruleDay=RULE_DAY)[0]
        print(f"  day-{RULE_DAY} rule flags {flag_stats['flagged']:,} of "
              f"{flag_stats['students']:,} registered students", flush=True)

        all_students = sorted(r['studentId'] for r in run('''
        MATCH (s:Student)-[:FIRST_INTERACTION]->(:Interaction {module: $module})
        RETURN DISTINCT s.id AS studentId
        ''', module=MODULE))
        shuffled = all_students[:]
        random.Random(SEED).shuffle(shuffled)
        HOLDOUT = sorted(shuffled[:int(len(shuffled) * HOLDOUT_FRACTION)])
        print(f'  {len(all_students):,} with a chain -> '
              f'{len(all_students) - len(HOLDOUT):,} train / {len(HOLDOUT):,} holdout',
              flush=True)

        gds.graph.project.cypher(
            graph_name=f'marg-{MODULE}', query=PROJECTION,
            query_parameters={'module': MODULE, 'maxDay': CUTOFF + SHIFT,
                              'holdout': HOLDOUT},
            overwrite=True)
        G = gds.graph.get(f'marg-{MODULE}')
        print(f'  {G.node_count():,} nodes, {G.relationship_count():,} rels', flush=True)

        observation = float(CUTOFF + SHIFT + 1)
        horizon = int(observation) + 10
        gds.fast_path.mutate(
            G, base_node_label='Student', event_node_label='Interaction',
            mutate_property='journeyEmbedding', embedding_dimension=128,
            lookback_horizon=horizon, num_time_anchors=20,
            event_node_categorical_properties=['activityTypeId'],
            event_node_feature_vector_property='features',
            event_node_time_property='day',
            first_relationship_type='FIRST_INTERACTION',
            next_relationship_type='NEXT_INTERACTION',
            observation_time=observation, smoothing_window=2,
            smoothing_rate=10.0 / horizon, random_seed=42)

        # After fast_path, never before -- it registers journeyEmbedding against
        # base_node_label only.
        for split_label, node_filter in [
            ('TrainStudent', 'n:Student AND n.isHoldout = 0'),
            ('HoldoutStudent', 'n:Student AND n.isHoldout = 1'),
        ]:
            gds.graph.node_labels.mutate(G, split_label, node_filter=node_filter)
        if 'journeyEmbedding' not in set(G.node_properties().get('TrainStudent', [])):
            raise SystemExit('TrainStudent lacks journeyEmbedding; labelling order wrong.')

        truth = gds.graph.node_properties.stream(
            G, 'passed', node_labels=['HoldoutStudent'])
        truth = truth.rename(columns={truth.columns[-1]: 'act'})[['nodeId', 'act']]
        rule = gds.graph.node_properties.stream(
            G, 'ruleFlagged', node_labels=['HoldoutStudent'])
        rule = rule.rename(columns={rule.columns[-1]: 'ruleFlagged'})[['nodeId', 'ruleFlagged']]

        for label, features in [('volume', ['logClicks']),
                                ('journey', ['journeyEmbedding', 'logClicks'])]:
            names = (f'marg-pipe-{MODULE}-{label}', f'marg-model-{MODULE}-{label}')
            for drop in (lambda: gds.model.get(names[1]).drop(),
                         lambda: gds.pipeline.node_classification.get(names[0]).drop()):
                try:
                    drop()
                except Exception:
                    pass
            pipe, _ = gds.pipeline.node_classification.create(names[0])
            pipe.select_features(features)
            pipe.configure_split(test_fraction=0.2, validation_folds=4)
            pipe.add_logistic_regression(penalty=(0.001, 1.0), max_epochs=300)
            pipe.add_random_forest(max_depth=(4, 16), number_of_decision_trees=200)
            model, _ = pipe.train(G, model_name=names[1],
                                  metrics=['F1_MACRO', 'ACCURACY'],
                                  target_property='passed',
                                  target_node_labels=['TrainStudent'], random_seed=42)

            preds = model.predict_stream(G, target_node_labels=['HoldoutStudent'])
            pcol = [c for c in preds.columns
                    if c != 'nodeId' and 'probab' not in c.lower()][-1]
            merged = (preds.rename(columns={pcol: 'pred'})[['nodeId', 'pred']]
                      .merge(truth, on='nodeId').merge(rule, on='nodeId'))

            whole = detection(merged)
            unflagged = detection(merged[merged.ruleFlagged == 0])
            already = detection(merged[merged.ruleFlagged == 1])
            records.append({'module': MODULE, 'features': label,
                            **{f'all_{k}': v for k, v in whole.items()},
                            **{f'new_{k}': v for k, v in unflagged.items()},
                            **{f'rule_{k}': v for k, v in already.items()}})
            print(f'    {label:8s} whole holdout   n {whole["n"]:,} | '
                  f'flagged {whole["flagged"]:,} caught {whole["caught"]:,} | '
                  f'precision {whole["precision"]:.3f} recall {whole["recall"]:.3f}')
            print(f'    {"":8s} rule NOT flagged n {unflagged["n"]:,} | '
                  f'flagged {unflagged["flagged"]:,} caught {unflagged["caught"]:,} | '
                  f'precision {unflagged["precision"]:.3f} recall {unflagged["recall"]:.3f}')
            print(f'    {"":8s} rule already got n {already["n"]:,} | '
                  f'flagged {already["flagged"]:,} caught {already["caught"]:,} | '
                  f'precision {already["precision"]:.3f} recall {already["recall"]:.3f}',
                  flush=True)
            for drop in (lambda: gds.model.get(names[1]).drop(),
                         lambda: gds.pipeline.node_classification.get(names[0]).drop()):
                try:
                    drop()
                except Exception:
                    pass
        try:
            G.drop()
        except Exception:
            pass

        total = 0
        while True:
            n = run('MATCH (i:Interaction {module: $m}) WITH i LIMIT 20000 '
                    'DETACH DELETE i RETURN count(*) AS n', m=MODULE)[0]['n']
            total += n
            if n == 0:
                break
        print(f'  removed {total:,} interaction nodes for {MODULE}\n', flush=True)
finally:
    print('=== teardown ===', flush=True)
    if gds is not None:
        try:
            gds.delete()
            print('session deleted')
        except Exception as error:
            print('session:', str(error)[:120])
    left = 0
    while True:
        n = run('MATCH (i:Interaction) WITH i LIMIT 20000 DETACH DELETE i '
                'RETURN count(*) AS n')[0]['n']
        left += n
        if n == 0:
            break
    run('MATCH (s:Student) WHERE s.passed IS NOT NULL OR s.ruleFlagged IS NOT NULL '
        'REMOVE s.passed, s.logClicks, s.ruleFlagged')
    t = run('MATCH (n) WITH count(n) AS nodes MATCH ()-[r]->() '
            'RETURN nodes, count(r) AS relationships')[0]
    print(f'removed {left:,} stray interaction nodes and the Student properties')
    print(f"graph totals: {t['nodes']:,} nodes, {t['relationships']:,} relationships")
    driver.close()

if records:
    f = pd.DataFrame(records).set_index(['module', 'features'])
    print('\n' + '=' * 88)
    print("THE MODEL'S MARGINAL VALUE (holdout students the day-7 rule did not flag)")
    print('=' * 88)
    print(f[['all_n', 'all_precision', 'all_recall',
             'new_n', 'new_precision', 'new_recall']].round(4).to_string())
    print('\nprecision lost when the rule takes its share first')
    print((f['all_precision'] - f['new_precision']).round(4).to_string())
    print('\non the students the rule already flagged')
    print(f[['rule_n', 'rule_at_risk', 'rule_precision', 'rule_recall']]
          .round(4).to_string())
