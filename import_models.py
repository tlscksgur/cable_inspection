"""Copy exported model bundles without loading checkpoints or executing configs.

Dry run by default. --apply copies verified artifacts and registers existing DBs.
"""
import argparse
import ast
import hashlib
import json
import shutil
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from store import Store


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def preflight(source, data, databases):
    source = Path(source).resolve(strict=True)
    data = Path(data).resolve(strict=True)
    if source == data or source in data.parents or data in source.parents:
        raise ValueError('Source and application data must be separate directories')
    plans = []
    for folder in sorted(source.glob('rtmins*')):
        if not folder.is_dir():
            continue
        info = json.loads((folder/'model_info.json').read_text(encoding='utf-8'))
        train = json.loads((folder/'train_info.json').read_text(encoding='utf-8'))
        if info['arch'] != 'rtmdet_ins' or train['size'] not in ('s', 'm', 'l', 'x'):
            raise ValueError(f'Unsupported model: {folder.name}')
        config = ast.parse((folder/'config.py').read_text(encoding='utf-8'))
        assignments = {n.targets[0].id: n.value for n in config.body
                       if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name)}
        classes = list(ast.literal_eval(assignments['classes']))
        if classes != info['classes'] or len(set(classes)) != len(classes):
            raise ValueError(f'Class metadata mismatch: {folder.name}')
        if ast.literal_eval(assignments['_base_']) != [
            f'/opt/mmdetection/configs/rtmdet/rtmdet-ins_{train["size"]}_8xb32-300e_coco.py'
        ]:
            raise ValueError(f'Unexpected base configuration: {folder.name}')
        checkpoint = folder/'model.pth'
        with checkpoint.open('rb') as stream:
            if stream.read(2) != b'PK':
                raise ValueError(f'Checkpoint is not a PyTorch ZIP archive: {folder.name}')
        cp_hash = digest(checkpoint)
        files = []
        destination = data/'models'/f'{folder.name}-{cp_hash[:12]}'
        for file in sorted(folder.iterdir()):
            if file.name.startswith('.'):
                continue
            if file.is_symlink() or not file.is_file() or file.suffix not in ('.pth', '.py', '.json', '.txt'):
                raise ValueError(f'Unexpected artifact: {file.name}')
            checksum = cp_hash if file == checkpoint else digest(file)
            target = destination/file.name
            if target.exists() and (not target.is_file() or digest(target) != checksum):
                raise ValueError(f'Destination conflict: {target}')
            files.append(dict(source=str(file), target=str(target), sha256=checksum,
                              bytes=file.stat().st_size))
        evaluations = {}
        for version, summary in info.get('evals', {}).items():
            evaluations[f'external:cksgur:v{version}'] = dict(
                version_name=f'v{version}', split='valid', source='imported',
                metrics={'coco/segm_mAP_50': summary.get('segm50'),
                         'coco/segm_mAP': summary.get('segm5095'),
                         'coco/bbox_mAP_50': summary.get('box50')},
                summary=summary)
        trained_eval = info.get('evals', {}).get(str(info['trained_on']), {})
        plans.append(dict(info=info, train=train, classes=classes, files=files,
                          destination=str(destination), id='import-'+cp_hash[:24],
                          checkpoint_sha256=cp_hash, evaluations=evaluations,
                          metrics={'best_mask_mAP50': trained_eval.get('segm50')}))
    if not plans:
        raise ValueError('No RTMDet-Ins model bundles found')
    db_paths = []
    for name in databases:
        db = (data/name).resolve(strict=True)
        if db.parent != data or db.suffix != '.sqlite':
            raise ValueError('Database must be an existing application SQLite file in data')
        with closing(sqlite3.connect(db.as_uri()+'?mode=ro', uri=True)) as connection:
            schema = connection.execute("SELECT value FROM studio_meta WHERE key='schema_version'").fetchone()
            if schema != ('1',):
                raise ValueError('Unrecognized application database')
            class_records = [json.loads(row[0]) for row in connection.execute(
                "SELECT payload FROM studio_records WHERE kind='classes' ORDER BY rowid")]
            if any(p['classes'] != [c['name'] for c in class_records] for p in plans):
                raise ValueError('Application/model class order mismatch')
        db_paths.append((db, class_records))
    return plans, db_paths


def run(source, data, databases, apply=False):
    plans, db_paths = preflight(source, data, databases)
    result = dict(applied=False, count=len(plans), databases=[str(x[0]) for x in db_paths],
                  models=[dict(name=p['train']['name'], trained_on=p['info']['trained_on'],
                               sha256=p['checkpoint_sha256'], files=len(p['files'])) for p in plans])
    if not apply:
        return result
    # Every source and destination is checked before copying the first artifact.
    for plan in plans:
        Path(plan['destination']).mkdir(parents=True, exist_ok=True)
        for file in plan['files']:
            target = Path(file['target'])
            if not target.exists():
                temporary = target.with_suffix(target.suffix+'.importing')
                with temporary.open('xb') as output, Path(file['source']).open('rb') as original:
                    shutil.copyfileobj(original, output)
                if digest(temporary) != file['sha256']:
                    raise ValueError(f'Copy verification failed: {target.name}')
                temporary.rename(target)
    imported_at = datetime.now(timezone.utc).isoformat()
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')
    for db, classes in db_paths:
        backup = db.parent/'backups'/f'{db.stem}-before-models-{stamp}.sqlite'
        backup.parent.mkdir(exist_ok=True)
        with closing(sqlite3.connect(db.as_uri()+'?mode=ro', uri=True)) as original, closing(sqlite3.connect(backup)) as copy:
            original.backup(copy)
        store = Store(db)
        existing = {m['id']:m for m in store.all('models')}
        models = []
        for p in plans:
            if p['id'] in existing:
                continue  # Idempotent: preserve user renames, active state and trash.
            info = p['info']; train = p['train']; dest = Path(p['destination'])
            models.append(dict(id=p['id'], name=train['name'], type='RTMDet-Ins', size=train['size'],
                               classes=classes, class_ids=[c['id'] for c in classes],
                               checkpoint=str(dest/'model.pth'), config=str(dest/'config.py'),
                               checkpoint_sha256=p['checkpoint_sha256'],
                               version_id=f'external:cksgur:v{info["trained_on"]}',
                               version_name=f'v{info["trained_on"]}', metrics=p['metrics'],
                               evaluations=p['evaluations'], original_model_info=info,
                               training_info=train, artifacts=[str(dest/Path(f['source']).name) for f in p['files']],
                               artifact_hashes={Path(f['source']).name:f['sha256'] for f in p['files']},
                               created=datetime.fromtimestamp(train['finished'], timezone.utc).isoformat(),
                               imported=imported_at, active=False, deleted=False))
        store.put_many('models', models)
        result.setdefault('registered', {})[db.name] = len(models)
    result['applied'] = True
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source'); parser.add_argument('--data-dir', required=True)
    parser.add_argument('--database', action='append', required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    print(json.dumps(run(args.source, args.data_dir, args.database, args.apply), ensure_ascii=False, indent=2))
