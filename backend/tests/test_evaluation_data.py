"""The datasets: scenarios, labels, checks, splits, review and the entity-level set.

Everything here runs on the fictional world, through the same code real records will use.
"""

import asyncio
import json
import random
import re

import pytest

from tessera.agents.crew import build_stack
from tessera.blackboard.store import EventStore
from tessera.devdata import FICTION_DATE
from tessera.errors import PolicyError
from tessera.evaluation.components import (
    contact_extraction,
    lookalike_detector,
    name_matcher,
)
from tessera.evaluation.entities import build_entity_items
from tessera.evaluation.firms import Firm, load_world
from tessera.evaluation.items import (
    EvalItem,
    Level,
    Split,
    content_hash,
    read_items,
    write_items,
)
from tessera.evaluation.labelling import policy_label, with_quotes_from
from tessera.evaluation.messages import build_message_items, import_written
from tessera.evaluation.review import (
    compare_labels,
    export_sheet,
    passes_far_enough_apart,
    read_sheet,
    settle,
)
from tessera.evaluation.scenarios import (
    lookalike,
    respelled,
    sample_scenarios,
    scenario_from_json,
    scenario_to_json,
)
from tessera.evaluation.splits import DEV_SHARE, assign_splits, balanced_sample, of_split
from tessera.evaluation.validators import (
    missing_facts,
    personal_data,
    stray_identifiers,
)
from tessera.evaluation.writing import (
    origin_mix,
    paraphrase_messages,
    render_template,
    writing_brief,
)
from tessera.governance.policies import load_decision_policy
from tessera.knowledge import load_activity_taxonomy
from tessera.llm.config import load_models_policy
from tessera.llm.testing import ScriptedTransport, chat_reply
from tessera.llm.types import TransientLLMError
from tessera.protocol.common import ResultCode

from .conftest import REPO_ROOT
from .scripted import in_loop

TODAY = FICTION_DATE
MODELS = load_models_policy(REPO_ROOT / "policies")


@pytest.fixture
def stack(populated_settings):
    return build_stack(populated_settings, ScriptedTransport([]), EventStore(), MODELS)


@pytest.fixture
def taxonomy(populated_settings):
    return load_activity_taxonomy(populated_settings.knowledge_dir)


@pytest.fixture
def world(stack, taxonomy):
    return load_world(stack.registry, taxonomy)


def item(item_id="M-1", **changes):
    fields = {
        "item_id": item_id,
        "level": Level.MESSAGE,
        "text": "An offer.",
        "gold_label": ResultCode.CONFLICTS,
        "origin": "template",
    }
    return EvalItem(**{**fields, **changes})


# ------------------------------------------------------------------ items


def test_what_a_system_receives_holds_no_gold():
    offer = item(gold_reasons=("HC1",), gold_relevant=("CMA",), factors=("F7",)).offer()
    dumped = offer.model_dump()
    assert not [key for key in dumped if "gold" in key]
    assert "HC1" not in str(dumped)
    assert offer.synthetic is True and offer.corpus_item_id == "M-1"


def test_a_restricted_item_cannot_be_written_outside_a_restricted_folder(tmp_path):
    with pytest.raises(PermissionError):
        write_items(tmp_path / "public" / "items.jsonl", [item(restricted=True)])
    written = tmp_path / "restricted" / "items.jsonl"
    write_items(written, [item(restricted=True)])
    assert read_items(written)[0].restricted is True


def test_items_survive_a_round_trip(tmp_path):
    original = [item("M-1", factors=("F1", "F2")), item("M-2", channel="whatsapp")]
    path = write_items(tmp_path / "items.jsonl", original) and tmp_path / "items.jsonl"
    assert read_items(path) == original


def test_a_hash_ignores_order_and_catches_any_change():
    a, b = item("M-1"), item("M-2")
    assert content_hash([a, b]) == content_hash([b, a])
    assert content_hash([a]) != content_hash([a.model_copy(update={"text": "Changed."})])


# ------------------------------------------------------------------ the world


def test_the_world_reads_every_list(world):
    assert {firm.regulator for firm in world.firms} == {"CMA", "DFSA", "VARA"}
    assert {entry.source_id for entry in world.listed} == {
        "cma_warnings",
        "vara_unlicensed",
        "dfsa_alerts",
    }


def test_dfsa_records_are_marked_restricted_and_others_are_not(world):
    for firm in world.firms:
        assert firm.restricted is (firm.regulator == "DFSA")


def test_a_short_name_drops_only_the_legal_ending(world):
    names = {firm.name: firm.short_name for firm in world.firms}
    assert names["Falcon Ridge Securities L.L.C."] == "Falcon Ridge Securities"
    assert names["Lumen Crest Capital (DIFC) Limited"] == "Lumen Crest Capital"


def test_demo_mode_leaves_dfsa_records_out(populated_settings, taxonomy):
    from tessera.config.settings import Mode

    from .conftest import make_settings

    demo = make_settings(populated_settings.data_path, Mode.RESTRICTED_DEMO)
    stack = build_stack(demo, ScriptedTransport([]), EventStore(), MODELS)
    world = load_world(stack.registry, taxonomy)
    assert not any(firm.restricted for firm in world.firms)
    assert not any(entry.restricted for entry in world.listed)


# ------------------------------------------------------------------ scenarios


def test_scenarios_are_reproducible(world):
    first = sample_scenarios(world, 12, seed=7)
    second = sample_scenarios(world, 12, seed=7)
    assert [s.slots for s in first] == [s.slots for s in second]


def test_scenarios_differ_by_seed(world):
    first = sample_scenarios(world, 12, seed=7)
    second = sample_scenarios(world, 12, seed=8)
    assert [s.slots for s in first] != [s.slots for s in second]


def test_scenarios_are_balanced_across_labels(world):
    scenarios = sample_scenarios(world, 15, seed=7)
    for label in ResultCode:
        assert sum(s.intended is label for s in scenarios) == 15


def test_every_recipe_family_appears(world):
    recipes = {s.recipe for s in sample_scenarios(world, 30, seed=7)}
    assert {"genuine", "copied_identifiers", "imitated_domain", "outside_the_licence"} <= recipes
    assert {"third_party_payment", "regulator_notice", "unknown_firm", "off_platform"} <= recipes


def test_every_registered_factor_has_a_recipe(world):
    """Fifteen scenario factors are registered (§11.2 B). None may go unused."""
    factors = {factor for s in sample_scenarios(world, 40, seed=7) for factor in s.factors}
    assert factors == {f"F{number}" for number in range(1, 16)}


def test_a_respelling_keeps_the_name_recognisable():
    assert respelled("Al Dhow Capital") == "El Dhow Capital"
    assert respelled("Harbour Cedar") == "Harbur Cedar"
    assert respelled("Azure Dhow Digital") == "Azure Dow Digital"
    assert respelled("Falcon Ridge") is None


def test_a_lookalike_differs_from_its_original_and_stays_reserved():
    rng = random.Random(3)
    for _ in range(50):
        fake = lookalike("falconridge.example", rng)
        assert fake != "falconridge.example" and fake.endswith(".example")


def test_the_wording_avoids_the_taxonomy_keywords(world, taxonomy):
    """Plain keywords are what let the rules baseline match the hand-written smoke set."""
    keywords = {word for activity in taxonomy.activities for word in activity.keywords}
    rng = random.Random(1)
    for scenario in sample_scenarios(world, 20, seed=7):
        text = render_template(scenario, rng).casefold()
        phrase = scenario.slots["activity"].casefold()
        assert phrase in text
        assert not [word for word in keywords if re.search(rf"{re.escape(word)}", phrase)]


def test_a_template_carries_everything_a_result_turns_on(world):
    rng = random.Random(2)
    for scenario in sample_scenarios(world, 20, seed=9):
        assert missing_facts(render_template(scenario, rng), scenario.keep) == []


def test_recipes_get_the_labels_they_intend(world, stack):
    """The policy decides, so a recipe that drifts from it is found here."""
    rng = random.Random(4)
    missed = []
    for scenario in sample_scenarios(world, 16, seed=11):
        text = render_template(scenario, rng)
        label = policy_label(
            stack, f"label-{scenario.scenario_id}", text, scenario.reading, today=TODAY
        )
        if label.result is not scenario.intended:
            missed.append((scenario.recipe, label.result.value))
    assert len(missed) <= 2, missed


def test_every_scenario_has_its_own_id(world):
    """Two results begin with the same letters, and a run keeps one record per ID."""
    names = [s.scenario_id for s in sample_scenarios(world, 30, seed=7)]
    assert len(set(names)) == len(names)


def test_repeated_ids_cannot_be_written(tmp_path):
    with pytest.raises(ValueError, match="repeat"):
        write_items(tmp_path / "items.jsonl", [item("M-1"), item("M-1")])


def test_an_invented_domain_is_never_one_somebody_could_own():
    rng = random.Random(1)
    for _ in range(50):
        assert lookalike("falconridge.ae", rng).endswith(".example")


def test_details_of_dfsa_firms_are_never_altered(world, stack, taxonomy):
    """The gateway would not recognise a changed value, so it would reach a model in clear."""
    recipes = {"variant_spelling", "imitated_domain", "injected_instruction"}
    for scenario in sample_scenarios(world, 40, seed=3):
        if scenario.recipe in recipes:
            assert not scenario.restricted
    built = build_entity_items(world, stack, taxonomy, today=TODAY, seed=1)
    assert not [card for card in built.items if card.stratum == "E11" and card.restricted]


def test_a_dfsa_firm_s_short_name_is_masked_before_any_model_sees_it(world, stack):
    for firm in world.of("DFSA"):
        assert firm.short_name not in stack.gateway.mask(f"Hello from {firm.short_name}.")


def test_an_injection_must_survive_rewording(world):
    scenarios = sample_scenarios(world, 40, seed=7)
    injected = [s for s in scenarios if "F15" in s.factors]
    assert injected and all(s.slots["aside"] in s.keep for s in injected)


def test_a_scenario_survives_being_saved(world):
    for scenario in sample_scenarios(world, 12, seed=7):
        assert scenario_from_json(json.loads(json.dumps(scenario_to_json(scenario)))) == scenario


def test_an_alert_finds_its_firm_despite_small_differences(world):
    assert world.firm_named("LUMEN CREST CAPITAL (DIFC) LTD").name.startswith("Lumen Crest")
    assert world.firm_named("Somebody Else Entirely") is None
    assert world.firm_named(None) is None


def test_a_legal_ending_must_be_a_whole_word():
    firm = Firm(
        "CMA", "1", "Wealth Unlimited", "active", None, None, None, None, None, (), (), False
    )
    assert firm.short_name == "Wealth Unlimited"


def test_a_paraphrase_may_reword_the_quotes_and_keep_the_reading(world):
    scenario = sample_scenarios(world, 1, seed=7)[0]
    changed = with_quotes_from(scenario.reading, "Completely new wording about the same offer.")
    assert changed.activities[0][1] == "Completely new wording about"


# ------------------------------------------------------------------ writing


def test_the_mix_of_sources_is_as_registered():
    origins = origin_mix(100, seed=1)
    assert origins.count("template") == 30
    assert origins.count("paraphrase") == 50
    assert origins.count("human") == 20


def test_a_paraphrase_request_lists_what_must_survive():
    system, user = paraphrase_messages("Text.", ("alpha.example", "Beta Ltd"))
    assert "exactly" in system["content"]
    assert "- alpha.example" in user["content"] and "- Beta Ltd" in user["content"]


def test_a_writing_brief_holds_no_label(world):
    brief = writing_brief(sample_scenarios(world, 1, seed=7)[0])
    assert not {"intended", "label", "gold", "recipe", "factors"} & set(brief)


def test_a_writing_brief_says_what_the_offer_is_about(world):
    scenario = sample_scenarios(world, 1, seed=7)[0]
    assert writing_brief(scenario)["offer_about"] == scenario.slots["activity"]


async def _no_people(stack, world, scenarios, **changes):
    arguments = {"today": TODAY, "seed": 5, "use_model": False, "people": False}
    return await build_message_items(scenarios, stack, world, **{**arguments, **changes})


@in_loop
async def test_messages_build_without_a_model(world, stack):
    scenarios = sample_scenarios(world, 8, seed=7)
    built = await _no_people(stack, world, scenarios)
    assert len(built.items) + len(built.dropped) == len(scenarios)
    assert {item.level for item in built.items} == {Level.MESSAGE}
    assert all(item.origin == "template" and item.synthetic for item in built.items)


@in_loop
async def test_a_label_comes_from_the_policy_with_its_reasons(world, stack):
    built = await _no_people(stack, world, sample_scenarios(world, 8, seed=7))
    conflicts = [item for item in built.items if item.gold_label is ResultCode.CONFLICTS]
    assert conflicts and all(item.gold_reasons for item in conflicts)
    assert all(reason.startswith("HC") for item in conflicts for reason in item.gold_reasons)


@in_loop
async def test_items_built_from_dfsa_facts_are_restricted(world, stack):
    built = await _no_people(stack, world, sample_scenarios(world, 18, seed=7))
    named = [item for item in built.items if "Lumen Crest" in item.text]
    assert named and all(item.restricted for item in named)


@in_loop
async def test_people_get_briefs_for_their_share(world, stack):
    scenarios = sample_scenarios(world, 10, seed=7)
    built = await _no_people(stack, world, scenarios, people=True)
    assert len(built.for_people) == round(len(scenarios) * 0.2)
    written = {
        scenario.scenario_id: "Our team at {} can help. {}".format(
            scenario.slots["firm"], " ".join(scenario.keep)
        )
        for scenario in built.for_people
        if scenario.slots.get("firm")
    }
    imported = import_written(written, built.for_people, stack, world, today=TODAY)
    assert imported.items or imported.dropped
    assert all(item.origin == "human" for item in imported.items)


@in_loop
async def test_a_paraphrase_goes_out_masked_and_comes_back_clear(world, populated_settings):
    seen = []

    def reply(payload):
        seen.append(payload["messages"][1]["content"])
        return chat_reply(payload["messages"][1]["content"].split("Message:\n")[1])

    transport = ScriptedTransport([reply] * 40)
    stack = build_stack(populated_settings, transport, EventStore(), MODELS)
    scenarios = [s for s in sample_scenarios(world, 30, seed=7) if s.restricted][:4]
    built = await build_message_items(
        scenarios, stack, world, today=TODAY, seed=5, use_model=True, people=False
    )
    assert seen and not [text for text in seen if "Lumen Crest" in text or "Harbour Cedar" in text]
    named = [item for item in built.items if item.origin == "paraphrase"]
    assert named and not [item for item in named if "⟦" in item.text]


@in_loop
async def test_a_failed_paraphrase_loses_only_itself(world, populated_settings):
    def reply(payload):
        if "fail" in seen:
            raise TransientLLMError("the provider went away")
        seen.append("fail")
        return chat_reply("")

    seen = []
    transport = ScriptedTransport([reply] * 40)
    stack = build_stack(populated_settings, transport, EventStore(), MODELS)
    built = await build_message_items(
        sample_scenarios(world, 8, seed=7),
        stack,
        world,
        today=TODAY,
        seed=5,
        use_model=True,
        people=False,
    )
    assert built.items, "what was built before the failures is kept"
    assert any("empty or repeated" in line for line in built.dropped)
    assert any("keeps failing" in line for line in built.dropped)


@in_loop
async def test_the_same_text_is_kept_once(world, stack):
    scenarios = sample_scenarios(world, 60, seed=7)
    built = await _no_people(stack, world, scenarios)
    texts = [item.text.casefold() for item in built.items]
    assert len(set(texts)) == len(texts)


# ------------------------------------------------------------------ checks


def test_a_missing_fact_is_named():
    assert missing_facts("Visit alpha.example today.", ("alpha.example", "Beta Ltd")) == [
        "missing 'Beta Ltd'"
    ]


def test_a_stray_domain_is_caught_and_a_reserved_one_is_not(world):
    scenario = sample_scenarios(world, 1, seed=7)[0]
    assert stray_identifiers("See invented-site.com for more.", scenario, world)
    assert not stray_identifiers("See invented-site.example for more.", scenario, world)


def test_a_register_domain_nobody_chose_is_caught(world):
    scenario = next(
        s for s in sample_scenarios(world, 6, seed=7) if "coralledger.example" not in s.keep
    )
    problems = stray_identifiers("Also see coralledger.example today.", scenario, world)
    assert problems == ["unexpected domain 'coralledger.example'"]


def test_a_firm_nobody_chose_is_caught(world):
    scenario = next(
        s for s in sample_scenarios(world, 6, seed=7) if "Silver Palm" not in " ".join(s.keep)
    )
    assert stray_identifiers("Backed by Silver Palm Advisers.", scenario, world)


def test_real_looking_personal_data_is_caught():
    assert personal_data("Pay with card 4111 1111 1111 1111.")
    assert personal_data("Mail me at someone@gmail.com")
    assert not personal_data("Call +44 7700 900123 today.")


# ------------------------------------------------------------------ splits


def make_items(count):
    labels = list(ResultCode)
    return [
        item(f"M-{index:03d}", gold_label=labels[index % 3], factors=(f"F{index % 2 + 1}",))
        for index in range(count)
    ]


def test_a_split_keeps_the_registered_share():
    assigned = assign_splits(make_items(300), seed=1)
    assert len(of_split(assigned, Split.DEV)) == round(300 * DEV_SHARE)
    assert len(of_split(assigned, Split.TEST)) == 210


def test_a_split_is_stratified():
    assigned = assign_splits(make_items(300), seed=1)
    for label in ResultCode:
        dev = [i for i in of_split(assigned, Split.DEV) if i.gold_label is label]
        assert len(dev) == pytest.approx(30, abs=1)


def test_a_split_is_reproducible_and_seeded():
    items = make_items(120)
    first = {i.item_id for i in of_split(assign_splits(items, seed=1), Split.DEV)}
    again = {i.item_id for i in of_split(assign_splits(items, seed=1), Split.DEV)}
    other = {i.item_id for i in of_split(assign_splits(items, seed=2), Split.DEV)}
    assert first == again and first != other


def test_a_sample_is_balanced_even_though_files_are_grouped():
    grouped = sorted(make_items(30), key=lambda i: i.gold_label.value)
    chosen = balanced_sample(grouped, 9, seed=1)
    assert len(chosen) == 9
    for label in ResultCode:
        assert sum(i.gold_label is label for i in chosen) == 3


def test_a_sample_copes_with_too_few_items():
    assert len(balanced_sample(make_items(4), 9, seed=1)) == 4


def test_small_strata_still_add_up():
    items = [item(f"M-{i}", factors=(f"F{i}",)) for i in range(20)]
    assert len(of_split(assign_splits(items, seed=1), Split.DEV)) == 6


# ------------------------------------------------------------------ review


def test_a_review_sheet_is_blind(tmp_path):
    secret = item(gold_reasons=("HC1",), factors=("F7",), stratum="E9")
    sheet = export_sheet([secret], tmp_path / "sheet.csv", annotator="A", seed=1)
    text = sheet.read_text(encoding="utf-8")
    assert "CONFLICTS" not in text and "HC1" not in text and "F7" not in text


def test_a_review_sheet_of_restricted_items_stays_restricted(tmp_path):
    with pytest.raises(PermissionError):
        export_sheet([item(restricted=True)], tmp_path / "a.csv", annotator="A", seed=1)
    path = tmp_path / "restricted" / "a.csv"
    assert export_sheet([item(restricted=True)], path, annotator="A", seed=1).exists()


def test_annotators_get_their_own_order(tmp_path):
    items = make_items(30)
    a = export_sheet(items, tmp_path / "a.csv", annotator="A", seed=1).read_text("utf-8")
    b = export_sheet(items, tmp_path / "b.csv", annotator="B", seed=1).read_text("utf-8")
    assert a != b


def test_a_filled_sheet_reads_back_and_a_bad_label_stops_it(tmp_path):
    path = tmp_path / "filled.csv"
    path.write_text("item_id,message,label,note\nM-1,Text,conflicts,\n", encoding="utf-8")
    assert read_sheet(path) == {"M-1": ResultCode.CONFLICTS}
    path.write_text("item_id,message,label,note\nM-1,Text,maybe,\n", encoding="utf-8")
    with pytest.raises(ValueError, match="M-1"):
        read_sheet(path)


def test_agreement_lists_what_needs_discussion():
    first = {"a": ResultCode.CONFLICTS, "b": ResultCode.CONSISTENT, "c": ResultCode.UNVERIFIED}
    second = {"a": ResultCode.CONFLICTS, "b": ResultCode.CONFLICTS, "c": ResultCode.UNVERIFIED}
    gold = {"a": ResultCode.CONSISTENT, "b": ResultCode.CONSISTENT, "c": ResultCode.UNVERIFIED}
    agreement = compare_labels(first, second, gold)
    assert agreement.disagreements == ("b",)
    assert agreement.against_policy == ("a",)
    assert agreement.meets_target is False


def test_one_annotators_two_passes_must_be_two_weeks_apart():
    from datetime import date

    assert not passes_far_enough_apart(date(2026, 11, 1), date(2026, 11, 10))
    assert passes_far_enough_apart(date(2026, 11, 1), date(2026, 11, 15))


def test_settling_changes_labels_and_lists_every_drop():
    items = [item("M-1"), item("M-2"), item("M-3")]
    kept, dropped = settle(items, {"M-1": ResultCode.UNVERIFIED, "M-2": None})
    assert dropped == ["M-2"]
    assert [i.item_id for i in kept] == ["M-1", "M-3"]
    assert kept[0].gold_label is ResultCode.UNVERIFIED


def test_a_changed_label_drops_reasons_that_belonged_to_the_old_one():
    kept, _ = settle([item("M-1", gold_reasons=("HC1",))], {"M-1": ResultCode.UNVERIFIED})
    assert kept[0].gold_reasons == ()
    same, _ = settle([item("M-1", gold_reasons=("HC1",))], {"M-1": ResultCode.CONFLICTS})
    assert same[0].gold_reasons == ("HC1",)


# ------------------------------------------------------------------ the components


def test_the_name_matcher_finds_variants_and_ignores_strangers(world, populated_settings):
    thresholds = load_decision_policy(populated_settings.policies_dir).thresholds
    score = name_matcher(world, thresholds)
    assert score.positives > len(world.firms)
    assert score.recall > 0.9
    assert score.false_alarms == 0


def test_the_lookalike_detector_catches_imitations_only(world, populated_settings):
    thresholds = load_decision_policy(populated_settings.policies_dir).thresholds
    score = lookalike_detector(world, thresholds, seed=1)
    assert score.recall > 0.9
    assert score.false_alarms == 0


def test_contact_extraction_finds_what_an_item_was_built_with(world, stack):
    built = asyncio.run(
        build_message_items(
            sample_scenarios(world, 12, seed=7),
            stack,
            world,
            today=TODAY,
            seed=5,
            use_model=False,
            people=False,
        )
    )
    score = contact_extraction(built.items)
    assert score.positives >= 30
    assert score.recall == 1.0


def test_a_missed_contact_counts_against_extraction():
    missed = item(contacts=("alpha.example",), text="Nothing to see here.")
    assert contact_extraction([missed]).recall == 0.0


def test_a_score_copes_with_nothing_to_measure():
    empty = contact_extraction([])
    assert empty.recall is None and empty.precision is None


# ------------------------------------------------------------------ the entity-level set


def test_the_entity_set_covers_its_strata(world, stack, taxonomy):
    built = build_entity_items(world, stack, taxonomy, today=TODAY, seed=1)
    strata = {card.stratum for card in built.items}
    assert {"E1", "E2", "E3", "E4", "E5", "E6", "E7", "E8", "E9"} <= strata


def test_each_stratum_gets_its_registered_label(world, stack, taxonomy):
    built = build_entity_items(world, stack, taxonomy, today=TODAY, seed=1)
    expected = {
        "E1": ResultCode.CONFLICTS,
        "E2": ResultCode.CONSISTENT,
        "E3": ResultCode.CONFLICTS,
        "E4": ResultCode.CONFLICTS,
        "E5": ResultCode.CONSISTENT,
        "E6": ResultCode.CONFLICTS,
        "E7": ResultCode.CONSISTENT,
        "E8": ResultCode.CONFLICTS,
        "E9": ResultCode.CONFLICTS,
    }
    assert built.disputed == ()
    for card in built.items:
        if card.stratum in expected:
            assert card.gold_label is expected[card.stratum], card.text


def test_e8_holds_only_category_five_firms(world, stack, taxonomy):
    built = build_entity_items(world, stack, taxonomy, today=TODAY, seed=1)
    cards = [card for card in built.items if card.stratum == "E8"]
    fives = {f.name for f in world.of("CMA") if "5" in f.category}
    assert cards
    assert all(any(name in card.text for name in fives) for card in cards)


def test_cards_from_dfsa_facts_are_restricted_and_others_are_not(world, stack, taxonomy):
    built = build_entity_items(world, stack, taxonomy, today=TODAY, seed=1)
    by_stratum = {card.stratum: card for card in built.items}
    assert by_stratum["E1"].restricted and by_stratum["E3"].restricted
    assert not by_stratum["E7"].restricted and not by_stratum["E9"].restricted


def test_firms_outside_phase_one_cannot_be_verified(world, stack, taxonomy):
    built = build_entity_items(
        world, stack, taxonomy, today=TODAY, seed=1, cbuae_names=("Amber Creek Bank PJSC",)
    )
    card = next(card for card in built.items if card.stratum == "E10")
    assert card.gold_label is ResultCode.UNVERIFIED and "U2" in card.gold_reasons


def test_a_near_miss_never_passes_as_the_firm(world, stack, taxonomy):
    built = build_entity_items(world, stack, taxonomy, today=TODAY, seed=1)
    misses = [card for card in built.items if card.stratum == "E11"]
    assert misses and not [card for card in misses if card.gold_label is ResultCode.CONSISTENT]


def test_a_bad_taxonomy_code_cannot_slip_through(taxonomy):
    from tessera.evaluation.entities import _activity

    with pytest.raises(StopIteration):
        _activity(taxonomy, "NO.SUCH.CODE")
    assert PolicyError  # the module's own error type stays importable for the command line
