"""硬件抽象与仿真器测试。"""

from __future__ import annotations

import time
import unittest

from hardware import (HardwareManager, SimulatedRelay, WiegandEncoder, parse_byte_command)


class DictConfig:
    def __init__(self, sections):
        self.sections = sections

    def get_section(self, section):
        return dict(self.sections.get(section, {}))


class HardwareTests(unittest.TestCase):
    def test_parse_byte_command(self):
        self.assertEqual(parse_byte_command('A0 01 02'), b'\xa0\x01\x02')
        self.assertEqual(parse_byte_command('A00102'), b'\xa0\x01\x02')
        self.assertEqual(parse_byte_command('0xA0,0x01'), b'\xa0\x01')

    def test_simulated_relay_pulse(self):
        relay = SimulatedRelay()
        relay.pulse(0.1)
        self.assertTrue(relay.state)
        time.sleep(0.22)
        self.assertFalse(relay.state)

    def test_wiegand_26bit(self):
        pulses = WiegandEncoder.encode_26bit(facility=12, card_number=3456)
        self.assertEqual(len(pulses), 26)
        self.assertTrue(all(gap == 100 for _, gap in pulses))

    def test_hardware_manager_unlock_and_health(self):
        events = []
        config = DictConfig({'Hardware': {'mode': 'simulator', 'unlock_duration': '0.1'}})
        manager = HardwareManager.from_config(config, events.append)
        self.assertTrue(manager.unlock())
        self.assertTrue(manager.relay.state)
        self.assertEqual(events[0].event, 'unlock')
        self.assertEqual(len(manager.health()), 5)
        time.sleep(0.22)
        self.assertFalse(manager.relay.state)
        manager.trigger_alarm(0.1)
        self.assertTrue(manager._alarm_active)
        time.sleep(0.22)
        self.assertFalse(manager._alarm_active)
        manager.shutdown()


if __name__ == '__main__':
    unittest.main(verbosity=2)
