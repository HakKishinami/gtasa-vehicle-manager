/* A reminder only: this module never deletes, moves or installs any files. */
(() => {
  const text = map => window.I18N.pick(map);

  function choose(matches) {
    return new Promise(resolve => {
      const dialog = document.createElement('dialog');
      dialog.className = 'install-existing-dialog';
      dialog.setAttribute('aria-labelledby', 'installExistingTitle');
      const title = document.createElement('h3');
      title.id = 'installExistingTitle';
      title.textContent = text({en: 'Existing vehicle mods found'});
      const description = document.createElement('p');
      description.textContent = text({
        en: 'These models are already installed, possibly from this mod or another version. Would you like to remove the old installation first? Review and delete it manually in the mod library. Continuing may overwrite files in the same folder or leave duplicates in different folders.'
      });
      const list = document.createElement('ul');
      list.className = 'install-existing-list';
      matches.forEach(match => {
        const row = document.createElement('li');
        const models = document.createElement('strong');
        models.textContent = match.models.join(', ').toUpperCase();
        const path = document.createElement('div');
        path.textContent = match.path;
        row.append(models, path);
        list.appendChild(row);
      });
      const actions = document.createElement('div');
      actions.className = 'install-existing-actions';
      let settled = false;
      const finish = action => {
        if (settled) return;
        settled = true;
        dialog.close();
        dialog.remove();
        resolve(action);
      };
      [
        ['library', {en: 'Review in mod library'}, 'btn-primary'],
        ['continue', {en: 'Install anyway'}, 'btn-secondary'],
        ['cancel', {en: 'Cancel'}, 'btn-secondary']
      ].forEach(([action, label, style]) => {
        const button = document.createElement('button');
        button.type = 'button';
        button.dataset.action = action;
        button.className = 'btn ' + style;
        button.textContent = text(label);
        button.addEventListener('click', () => finish(action));
        actions.appendChild(button);
      });
      dialog.addEventListener('cancel', event => { event.preventDefault(); finish('cancel'); });
      dialog.addEventListener('close', () => finish('cancel'));
      dialog.append(title, description, list, actions);
      document.body.appendChild(dialog);
      dialog.showModal();
    });
  }

  async function beforeInstall(payload) {
    const response = await fetch('/api/installer/check-existing', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({target_model: payload.target_model, vehicles: payload.vehicles})
    });
    const data = await response.json();
    if (!data.success) throw new Error(data.error || text({en: 'Could not check existing installations'}));
    const matches = data.matches || [];
    return {action: matches.length ? await choose(matches) : 'continue', matches};
  }
  window.InstallReminder = {beforeInstall};
})();
