# DN-automate

Bot delta neutre cross-DEX : il repère les écarts de funding entre Hyperliquid (dont les
actions trade.xyz en HIP-3) et Arcus, puis, dans les étapes suivantes, ouvrira et fermera
les deux jambes automatiquement.

**État actuel : étape 1, scanner en lecture seule.** Il ne place aucun ordre et n'a besoin
d'aucune clé : il lit uniquement les API publiques.

## Ce que fait le scanner

À chaque passage (toutes les 60 s par défaut), pour chaque paire et chaque couple de
plateformes :

1. il lit le funding horaire, le prix, les frais taker et le carnet d'ordres ;
2. il se place long là où le funding est le plus bas et short là où il est le plus haut ;
3. il simule l'entrée et la sortie dans les carnets pour la taille visée (300 USD par jambe
   par défaut), ajoute les frais des 4 ordres et l'écart de prix entre plateformes ;
4. il calcule le temps de remboursement `H_be = coût d'aller-retour / gain horaire` ;
5. il vérifie les critères : écart annualisé minimum, stabilité sur 24 h, 3 j, 7 j et 30 j
   (seules les fenêtres où l'historique existe comptent, Arcus étant récent), glissement
   d'entrée maximum, marché ouvert ;
6. il classe les opportunités (celles qui passent d'abord, par `H_be` croissant), les
   affiche et les enregistre dans SQLite.

Frais pris en compte :

- **Hyperliquid** : frais taker configurés (palier 0 avec la remise de staking), doublés sur
  les marchés HIP-3 trade.xyz, divisés par 10 quand l'actif est en `growthMode`.
- **Arcus** : frais du palier configuré, lus dans `GET /v1/feetiers`.

Hors séance (signalé par Arcus via `isOutsideRth`), la marge de sécurité sur le coût de
sortie est élargie.

## Utilisation

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
cp config.example.toml config.toml   # puis ajuster la liste des paires
dn-bot scan --once                    # un passage
dn-bot scan                           # en continu
```

## Structure

```
src/dn_bot/
  config.py              chargement de config.toml
  models.py              carnet, funding, état d'un marché
  exchanges/             un adaptateur par plateforme (lecture seule pour l'instant)
    hyperliquid.py       POST /info : metaAndAssetCtxs, l2Book, fundingHistory
    arcus.py             GET /v1/markets, /v1/l2OrderBook, /v1/fundingRates, /v1/feetiers
  scanner/
    depth.py             simulation de remplissage dans un carnet
    funding.py           moyennes de funding par fenêtre
    ranking.py           coûts, temps de remboursement, critères, classement
    runner.py            boucle du scanner
    report.py            affichage du classement
  storage.py             enregistrement SQLite
tests/                   tests unitaires (faux adaptateurs, réponses d'API simulées)
```

## Tests

```bash
ruff check . && ruff format --check . && pytest
```

## Prochaines étapes

2. Dashboard web et alertes Telegram.
3. Exécuteur et clôtureur en simulation.
4. Ordres réels sur testnet, puis petites tailles.
5. Variational dès que son API de trading sort.
