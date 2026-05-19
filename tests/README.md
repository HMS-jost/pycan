# Tests

Run hardware-free unit tests from the repository root:

```powershell
python -m unittest discover -s tests -p "test_*.py"
```

The manual hardware integration suite needs three physical interfaces connected
to the same terminated CAN bus (CAN@net NT 420 uses CAN3, Basic devices use CAN1).
Optionally add a fourth node via IXXAT VCI (`--vci`):

```powershell
python tests/can_matrix_test.py --ascii-tcp 10.41.18.108 --ascii-udp 10.41.18.102 --tlv-udp 10.41.18.101 --tests all
python tests/can_matrix_test.py --ascii-tcp 10.41.18.108 --ascii-udp 10.41.18.102 --tlv-udp 10.41.18.101 --vci A0785D79 --tests all
```

Useful variants:

```powershell
python tests/can_matrix_test.py --ascii-tcp 10.41.18.10 --ascii-udp 10.41.18.11 --tlv-udp 10.41.18.12 --tests smoke,filters
python tests/can_matrix_test.py --ascii-tcp 10.41.18.10 --ascii-udp 10.41.18.11 --tlv-udp 10.41.18.12 --tests bitrates --bitrates 125,250,500,1000
python tests/can_matrix_test.py --ascii-tcp 10.41.18.10 --ascii-udp 10.41.18.11 --tlv-udp 10.41.18.12 --tests types --include-fd --bitrate 500 --data-bitrate 2000
python tests/can_matrix_test.py --ascii-tcp 10.41.18.10 --ascii-udp 10.41.18.11 --tlv-udp 10.41.18.12 --tests burst --burst-count 128
```
