# Upgrade

```bash
pip install --upgrade location-floor-plan
nautobot-server migrate location_floor_plan
nautobot-server post_upgrade
nautobot-server collectstatic --no-input
sudo systemctl restart nautobot nautobot-worker nautobot-scheduler
nautobot-server audit_location_floor_plan
```

After upgrading, review `PLUGINS_CONFIG["location_floor_plan"]` for threshold and background limit settings. Run `audit_location_floor_plan --cleanup` only after reviewing reported stale placements.
