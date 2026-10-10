# Synchronisation GitHub Actions

Le workflow est préparé localement. Il doit être publié sur la branche par défaut
du dépôt avant d'être disponible dans GitHub. Aucun push n'est effectué automatiquement.

## Configuration

Dans le dépôt GitHub, ouvrez **Settings → Secrets and variables → Actions → Secrets → New repository secret**.
Créez les quatre secrets suivants (ne mettez pas les valeurs dans le dépôt) :

| Nom | Valeur |
| --- | --- |
| `ADE_ICS_URL` | Le lien ADE de votre `.env` |
| `GOOGLE_CALENDAR_ID` | L'identifiant du calendrier de votre `.env` |
| `WORKFORCE_STATE_JSON` | Le contenu complet de `playwright/.auth/workforce.json` |
| `GOOGLE_WRITE_TOKEN_JSON` | Le contenu complet de `secrets/google-write-token.json` |

Aucun mot de passe Workforce n'est nécessaire. Le jeton Google contient déjà
les informations nécessaires au renouvellement : le fichier client OAuth n'est pas requis.

Pour la séparation EILCO / Domino's, ajoutez aussi `GOOGLE_ADE_CALENDAR_ID`
(identifiant d'EILCO) et `GOOGLE_WORKFORCE_CALENDAR_ID` (identifiant de Domino's).
Les deux doivent être renseignés ; ils remplacent le calendrier unique pour la
synchronisation. Conservez l'ancien `GOOGLE_CALENDAR_ID` pour référence.
Effectuez d'abord la migration locale documentée dans le README, avec
`ENABLE_REMOTE_SYNC=false`, puis testez le workflow avant de réactiver la variable.

Pour les six catégories EILCO, ajoutez aussi les six **Repository secrets** :

| Agenda | Nom du secret |
| --- | --- |
| EILCO – IA | `GOOGLE_ADE_IA_CALENDAR_ID` |
| EILCO – Data Science | `GOOGLE_ADE_DATA_CALENDAR_ID` |
| EILCO – Cours communs | `GOOGLE_ADE_COMMON_CALENDAR_ID` |
| EILCO – Anglais | `GOOGLE_ADE_ENGLISH_CALENDAR_ID` |
| EILCO – Examens | `GOOGLE_ADE_EXAMS_CALENDAR_ID` |
| EILCO – Vacances | `GOOGLE_ADE_HOLIDAYS_CALENDAR_ID` |

Copiez uniquement la valeur après `=` de chaque ligne correspondante de votre
`.env`. Ne copiez pas tout le fichier. Configurez les six secrets avant de lancer
un job : si aucun n'est configuré, le mode à deux agendas reste actif.
La migration `google_migrate --categories --apply` doit être terminée avant le
premier test et la réactivation de la programmation.

## Premier test et activation

1. Publiez les fichiers du projet et du workflow sur la branche par défaut après vérification.
2. Ouvrez **Actions → Unified Schedule → Run workflow**. Cette exécution synchronise réellement Google.
3. Vérifiez que l'exécution réussit. Workforce peut refuser une session provenant d'un autre réseau.
4. Dans **Settings → Secrets and variables → Actions → Variables**, créez `ENABLE_REMOTE_SYNC` avec la valeur `true`.
5. Après ce test réussi, désactivez la tâche locale **Unified Schedule - Hourly Sync** dans le Planificateur Windows.

Le workflow est programmé à la minute 17 de chaque heure UTC. Avant l'activation
de la variable, seul le lancement manuel fonctionne. Pour arrêter les exécutions
programmées, mettez la variable à `false`. GitHub peut retarder ou omettre des
exécutions programmées ; les dépôts publics inactifs pendant 60 jours voient leurs
workflows programmés désactivés.

## Sessions et données

Votre PC peut rester éteint. Si Workforce expire/refuse sa session, reconnectez-vous
localement avec `python -m unified_schedule.workforce --login`, puis remplacez
`WORKFORCE_STATE_JSON`. Pour renouveler Google, utilisez `authorize --write --login`
et remplacez `GOOGLE_WRITE_TOKEN_JSON`. Le mode OAuth Google « Testing » peut imposer
une expiration du jeton de renouvellement après sept jours.

Chaque machine GitHub est neuve : SQLite et les exports sont reconstruits à chaque
exécution, sans historique SQLite persistant. Google conserve les événements et
leurs identifiants stables, ce qui permet de les reconnaître sans doublons.
Les événements manquants ne sont pas supprimés. Les sessions renouvelées pendant
une exécution ne sont pas réinjectées dans les secrets GitHub ; une mise à jour
manuelle peut donc rester nécessaire. Aucun fichier de session, calendrier ou
journal détaillé n'est publié comme artifact. Les logs montrent seulement le bilan
ou une erreur générale, pour éviter d'exposer le planning dans un dépôt public.
Consultez les exécutions Actions pour les erreurs et configurez vos notifications
GitHub si vous souhaitez être informé des échecs. Aucune nouvelle alerte n'est envoyée par l'application.

Documentation : [programmation GitHub Actions](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule).
