from app.profiles import ROOT, load_profiles, skill_path


def test_supervisor_and_reviewer_use_separate_versioned_packages():
    profiles = load_profiles()
    supervisor, reviewer = profiles['SUPERVISOR'], profiles['REVIEWER']
    assert supervisor['id'] == 'SUPERVISOR'
    assert reviewer['id'] == 'REVIEWER'
    assert supervisor['version'] and reviewer['version']
    assert supervisor['knowledge'] != profiles['PRODUCER']['knowledge']
    assert reviewer['knowledge'] != profiles['QUALITY']['knowledge']
    assert supervisor['tools'] == ['read_file', 'task']
    assert reviewer['tools'] == ['read_file', 'submit_review']
    assert supervisor['domainVerified'] is False and reviewer['domainVerified'] is False
    assert supervisor['sha256'] != profiles['PRODUCER']['sha256']
    assert reviewer['sha256'] != profiles['QUALITY']['sha256']


def test_every_skill_name_matches_valid_directory_and_old_snapshot_is_preserved():
    profiles = load_profiles()
    assert len(profiles) == 21
    for role, profile in profiles.items():
        directory = role.lower().replace('_', '-') + '-skill'
        assert skill_path(profile) == f'/skills/{directory}/SKILL.md'
        assert (ROOT / directory / 'SKILL.md').is_file()
    old = dict(profiles['ANALYST'])
    old['skill'] = old['skill'].replace('name: analyst-skill\n', 'name: analyst-production\n', 1)
    assert skill_path(old) == '/skills/analyst-production/SKILL.md'
