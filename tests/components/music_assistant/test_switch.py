"""Test Music Assistant switch entities."""

from unittest.mock import AsyncMock, MagicMock, call, patch

from music_assistant_models.dsp import DSPConfig
from music_assistant_models.enums import EventType
from music_assistant_models.event import MassEvent
import pytest
from syrupy.assertion import SnapshotAssertion

from homeassistant.components.music_assistant.const import DOMAIN
from homeassistant.components.music_assistant.switch import PLAYER_OPTIONS_SWITCH
from homeassistant.components.switch import DOMAIN as SWITCH_DOMAIN, SwitchService
from homeassistant.const import (
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
    CommonServiceArgument,
    EntityCategory,
    Platform,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.translation import LOCALE_EN, async_get_translations

from .common import (
    create_player_queues_from_fixture,
    setup_integration_from_fixtures,
    snapshot_music_assistant_entities,
    trigger_subscription_callback,
)


@pytest.mark.parametrize("schema_version", [1, 101])
async def test_switch_entities(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    snapshot: SnapshotAssertion,
    music_assistant_client: MagicMock,
    schema_version: int,
) -> None:
    """Test switch entities, with the queue switches on servers that support them."""
    music_assistant_client.server_info.schema_version = schema_version
    await setup_integration_from_fixtures(hass, music_assistant_client)
    snapshot_music_assistant_entities(hass, entity_registry, snapshot, Platform.SWITCH)


async def test_switch_action(
    hass: HomeAssistant,
    music_assistant_client: MagicMock,
) -> None:
    """Test switch set action."""
    mass_player_id = "00:00:00:00:00:01"
    mass_option_key = "enhancer"
    entity_id = "switch.test_player_1_enhancer"

    await setup_integration_from_fixtures(hass, music_assistant_client)
    state = hass.states.get(entity_id)
    assert state
    assert state.state == STATE_OFF

    # toggle off -> on and verify, that client got called once with correct parameters
    await hass.services.async_call(
        SWITCH_DOMAIN,
        SwitchService.TOGGLE,
        {CommonServiceArgument.ENTITY_ID: entity_id},
        blocking=True,
    )
    assert music_assistant_client.send_command.call_count == 1
    assert music_assistant_client.send_command.call_args == call(
        "players/cmd/set_option",
        player_id=mass_player_id,
        option_key=mass_option_key,
        option_value=True,
    )


async def test_external_update(
    hass: HomeAssistant,
    music_assistant_client: MagicMock,
) -> None:
    """Test external value update."""
    mass_player_id = "00:00:00:00:00:01"
    mass_option_key = "enhancer"
    entity_id = "switch.test_player_1_enhancer"

    await setup_integration_from_fixtures(hass, music_assistant_client)

    # get current option and remove it
    switch_option = next(
        option
        for option in music_assistant_client.players._players[mass_player_id].options
        if option.key == mass_option_key
    )
    music_assistant_client.players._players[mass_player_id].options.remove(
        switch_option
    )

    # set new value different from previous one
    previous_value = switch_option.value
    assert isinstance(previous_value, bool)
    switch_option.value = not previous_value
    music_assistant_client.players._players[mass_player_id].options.append(
        switch_option
    )

    # verify old HA state before trigger
    state = hass.states.get(entity_id)
    assert state
    assert state.state == STATE_OFF

    await trigger_subscription_callback(
        hass, music_assistant_client, EventType.PLAYER_OPTIONS_UPDATED, mass_player_id
    )

    # verify new HA state after trigger
    state = hass.states.get(entity_id)
    assert state
    assert state.state == STATE_ON


async def test_ignored(
    hass: HomeAssistant,
    music_assistant_client: MagicMock,
    entity_registry: er.EntityRegistry,
) -> None:
    """Test that non-compatible player options are ignored."""
    config_entry = await setup_integration_from_fixtures(hass, music_assistant_client)
    registry_entries = er.async_entries_for_config_entry(
        entity_registry, config_entry_id=config_entry.entry_id
    )
    # only a single player option available
    assert sum(1 for entry in registry_entries if entry.domain == SWITCH_DOMAIN) == 1


async def test_name_translation_availability(
    hass: HomeAssistant,
) -> None:
    """Verify available translation keys are in strings.json."""
    # verify, that PLAYER_OPTIONS_TRANSLATION_KEYS_SWITCH matches strings.json
    translations = await async_get_translations(
        hass, language=LOCALE_EN, category="entity", integrations=[DOMAIN]
    )
    prefix = f"component.{DOMAIN}.entity.{Platform.SWITCH.value}."
    for translation_key in PLAYER_OPTIONS_SWITCH:
        assert translations.get(f"{prefix}{translation_key}.name") is not None, (
            f"{translation_key} is missing in strings.json for platform switch"
        )


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_dsp_switch(
    hass: HomeAssistant,
    music_assistant_client: MagicMock,
) -> None:
    """Test the DSP switch keeps the player's DSP settings when switching."""
    music_assistant_client.server_info.schema_version = 101
    config = music_assistant_client.config
    config.get_player_dsp_config = AsyncMock(
        return_value=DSPConfig(enabled=True, preset_id="night")
    )
    config.save_player_dsp_config = AsyncMock()
    await setup_integration_from_fixtures(hass, music_assistant_client)
    entity_id = "switch.test_player_1_dsp"
    state = hass.states.get(entity_id)
    assert state
    assert state.state == STATE_ON

    await hass.services.async_call(
        SWITCH_DOMAIN,
        SwitchService.TURN_OFF,
        {CommonServiceArgument.ENTITY_ID: entity_id},
        blocking=True,
    )
    assert config.save_player_dsp_config.call_args == call(
        "00:00:00:00:00:01", DSPConfig(enabled=False, preset_id="night")
    )

    # the switch follows the config the server reports
    await trigger_subscription_callback(
        hass,
        music_assistant_client,
        EventType.PLAYER_DSP_CONFIG_UPDATED,
        "00:00:00:00:00:01",
        DSPConfig(enabled=False, preset_id="night").to_dict(),
    )
    state = hass.states.get(entity_id)
    assert state
    assert state.state == STATE_OFF

    # a group applies the DSP of each member
    assert hass.states.get("switch.test_group_player_1_dsp") is None


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_dsp_switch_update_while_loading(
    hass: HomeAssistant,
    music_assistant_client: MagicMock,
) -> None:
    """Test an update that arrives while loading wins over the older response."""
    music_assistant_client.server_info.schema_version = 101

    async def config_while_loading(player_id: str) -> DSPConfig:
        on_config_updated = next(
            sub.args[0]
            for sub in music_assistant_client.subscribe.call_args_list
            if sub.args[1:] == (EventType.PLAYER_DSP_CONFIG_UPDATED, player_id)
        )
        on_config_updated(
            MassEvent(
                EventType.PLAYER_DSP_CONFIG_UPDATED,
                object_id=player_id,
                data=DSPConfig(enabled=True).to_dict(),
            )
        )
        return DSPConfig(enabled=False)

    music_assistant_client.config.get_player_dsp_config = AsyncMock(
        side_effect=config_while_loading
    )
    await setup_integration_from_fixtures(hass, music_assistant_client)
    state = hass.states.get("switch.test_player_1_dsp")
    assert state
    assert state.state == STATE_ON


async def test_dsp_switch_registry(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    music_assistant_client: MagicMock,
) -> None:
    """Test the DSP switch is a disabled config entity."""
    music_assistant_client.server_info.schema_version = 101
    await setup_integration_from_fixtures(hass, music_assistant_client)
    entry = entity_registry.async_get("switch.test_player_1_dsp")
    assert entry
    assert entry.unique_id == "00:00:00:00:00:01_dsp"
    assert entry.entity_category is EntityCategory.CONFIG
    assert entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION


@pytest.mark.parametrize(
    ("entity_id", "command", "argument"),
    [
        (
            "switch.test_player_1_crossfade",
            "player_queues/crossfade",
            "crossfade_enabled",
        ),
        (
            "switch.test_player_1_autoplay",
            "player_queues/autoplay",
            "autoplay_enabled",
        ),
    ],
)
@pytest.mark.parametrize(
    ("service", "enabled"),
    [(SwitchService.TURN_ON, True), (SwitchService.TURN_OFF, False)],
)
async def test_queue_switch_action(
    hass: HomeAssistant,
    music_assistant_client: MagicMock,
    entity_id: str,
    command: str,
    argument: str,
    service: str,
    enabled: bool,
) -> None:
    """Test a queue switch sets the setting of the player's own queue."""
    music_assistant_client.server_info.schema_version = 101
    await setup_integration_from_fixtures(hass, music_assistant_client)
    await hass.services.async_call(
        SWITCH_DOMAIN,
        service,
        {CommonServiceArgument.ENTITY_ID: entity_id},
        blocking=True,
    )
    assert music_assistant_client.send_command.call_args == call(
        command, queue_id="00:00:00:00:00:01", **{argument: enabled}, require_schema=101
    )


async def test_queue_switch_follows_queue(
    hass: HomeAssistant,
    music_assistant_client: MagicMock,
) -> None:
    """Test a queue switch follows its queue, from the moment the server adds it."""
    music_assistant_client.server_info.schema_version = 101
    # the server registers the player before its queue
    with patch(
        "tests.components.music_assistant.common.create_player_queues_from_fixture",
        return_value=[],
    ):
        await setup_integration_from_fixtures(hass, music_assistant_client)
    entity_id = "switch.test_player_1_crossfade"
    state = hass.states.get(entity_id)
    assert state
    assert state.state == STATE_UNAVAILABLE

    queue = {queue.queue_id: queue for queue in create_player_queues_from_fixture()}[
        "00:00:00:00:00:01"
    ]
    queue.crossfade_enabled = True
    music_assistant_client.player_queues._queues[queue.queue_id] = queue
    await trigger_subscription_callback(
        hass, music_assistant_client, EventType.QUEUE_ADDED, queue.queue_id
    )
    state = hass.states.get(entity_id)
    assert state
    assert state.state == STATE_ON

    queue.crossfade_enabled = False
    await trigger_subscription_callback(
        hass, music_assistant_client, EventType.QUEUE_UPDATED, queue.queue_id
    )
    state = hass.states.get(entity_id)
    assert state
    assert state.state == STATE_OFF
