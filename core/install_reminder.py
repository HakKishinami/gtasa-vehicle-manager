"""Read-only installed-model check used by the install confirmation UI."""
import os


def check_existing_models(game_path, params):
    vehicles = params.get('vehicles')
    if not isinstance(vehicles, list) or not vehicles:
        vehicles = [{'target_model': params.get('target_model', '')}]
    models = {str(v.get('target_model') or '').strip().lower()
              for v in vehicles if not v.get('skip')}
    models.discard('')
    matches = {}
    if not game_path or not os.path.isdir(game_path) or not models:
        return {'success': True, 'matches': []}
    root = os.path.join(game_path, 'modloader')
    if not os.path.exists(root):
        return {'success': True, 'matches': []}
    def scan_error(error):
        raise error
    # Match deployed vehicle models, not archive/folder names or vanilla IDs.
    # Do not traverse directory links out of the selected ModLoader tree.
    for directory, dirs, names in os.walk(root, followlinks=False, onerror=scan_error):
        dirs[:] = [name for name in dirs if not os.path.islink(os.path.join(directory, name))
                   and not getattr(os.path, 'isjunction', lambda _: False)(os.path.join(directory, name))]
        for name in names:
            model, extension = os.path.splitext(name.lower())
            if extension == '.dff' and model in models:
                matches.setdefault(directory, set()).add(model)
    return {'success': True, 'matches': [
        {'path': directory, 'models': sorted(found)}
        for directory, found in sorted(matches.items(), key=lambda item: item[0].lower())
    ]}
