"""
Django management command to run the MYCOIN Mempool Processor.

Continuously monitors the active Mempool at a configured interval (default: 30 seconds),
filters eligible transactions, enforces database-level concurrency locks,
and coordinates batch selection without Celery or external brokers.

Usage:
    # Run continuously (default 30-second interval, batch size 50)
    python manage.py run_mempool_processor

    # Custom interval and batch size
    python manage.py run_mempool_processor --interval 15 --batch-size 100

    # Single-run execution (inspects/processes current mempool batch once and exits)
    python manage.py run_mempool_processor --single-run

    # Target a specific blockchain chain ID
    python manage.py run_mempool_processor --chain-id 2026
"""

import logging
import os
import signal
import threading
import time
from typing import Optional

from django.core.management.base import BaseCommand
from django.utils import timezone

from ledger.services.mempool_processor import (
    DEFAULT_BATCH_SIZE,
    DEFAULT_INTERVAL_SECONDS,
    MempoolProcessingResult,
    process_mempool,
)

logger = logging.getLogger("ledger.mempool_processor")


class Command(BaseCommand):
    help = (
        "Continuously monitors the MYCOIN Mempool every 30 seconds (configurable) "
        "and coordinates transaction batch selection for upcoming block production."
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.stop_event = threading.Event()

    def add_arguments(self, parser):
        parser.add_argument(
            "--interval",
            type=int,
            default=DEFAULT_INTERVAL_SECONDS,
            help=f"Processing cycle interval in seconds (default: {DEFAULT_INTERVAL_SECONDS}s).",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=DEFAULT_BATCH_SIZE,
            help=f"Maximum number of transactions per processing batch (default: {DEFAULT_BATCH_SIZE}).",
        )
        parser.add_argument(
            "--chain-id",
            type=int,
            default=None,
            help="Optional chain ID of the target blockchain (defaults to first active blockchain).",
        )
        parser.add_argument(
            "--single-run",
            action="store_true",
            default=False,
            help="Run a single mempool check cycle and exit immediately (useful for testing/cron).",
        )
        parser.add_argument(
            "--max-iterations",
            type=int,
            default=None,
            help="Optional limit on the number of cycles before cleanly terminating (useful for tests).",
        )

    def _setup_signal_handlers(self):
        """Attaches graceful termination handlers for SIGINT (Ctrl+C) and SIGTERM."""
        def _handle_signal(signum, frame):
            sig_name = signal.Signals(signum).name if hasattr(signal, "Signals") else str(signum)
            self.stdout.write(
                self.style.WARNING(f"\n[MempoolProcessor] Received {sig_name}. Stopping gracefully...")
            )
            logger.info("Termination signal received (%s). Triggering graceful shutdown...", sig_name)
            self.stop_event.set()

        try:
            signal.signal(signal.SIGINT, _handle_signal)
            signal.signal(signal.SIGTERM, _handle_signal)
        except (ValueError, AttributeError):
            # When executed in non-main threads (e.g. some test runners)
            pass

    def handle(self, *args, **options):
        interval = max(0, options["interval"])
        batch_size = max(1, options["batch_size"])
        chain_id: Optional[int] = options["chain_id"]
        single_run: bool = options["single_run"]
        max_iterations: Optional[int] = options["max_iterations"]

        self._setup_signal_handlers()

        pid = os.getpid()
        mode_str = "Single-run" if single_run else f"Continuous (interval: {interval}s)"
        self.stdout.write(
            self.style.SUCCESS(
                f"==========================================================\n"
                f" MYCOIN Mempool Processor Started\n"
                f" PID: {pid} | Mode: {mode_str} | Batch Size: {batch_size}\n"
                f" Chain ID: {chain_id if chain_id is not None else 'Default Active'}\n"
                f"=========================================================="
            )
        )
        logger.info(
            "Mempool processor started [PID: %d, Mode: %s, Interval: %ds, BatchSize: %d, ChainID: %s]",
            pid,
            mode_str,
            interval,
            batch_size,
            chain_id,
        )

        iteration = 0
        try:
            while not self.stop_event.is_set():
                iteration += 1
                cycle_start_time = time.time()
                timestamp_str = timezone.now().strftime("%Y-%m-%d %H:%M:%S UTC")

                self.stdout.write(
                    f"\n[{timestamp_str}] [Cycle #{iteration}] Checking mempool..."
                )

                try:
                    result: MempoolProcessingResult = process_mempool(
                        batch_size=batch_size,
                        chain_id=chain_id,
                    )
                    self._report_result(result)
                except Exception as exc:
                    logger.exception(
                        "Unexpected error encountered during mempool processing cycle #%d: %s",
                        iteration,
                        exc,
                    )
                    self.stderr.write(
                        self.style.ERROR(
                            f"[Cycle #{iteration}] Processing error: {exc}"
                        )
                    )

                if single_run:
                    self.stdout.write(self.style.NOTICE("Single-run completed. Exiting."))
                    break

                if max_iterations is not None and iteration >= max_iterations:
                    self.stdout.write(
                        self.style.NOTICE(f"Reached maximum requested iterations ({max_iterations}). Exiting.")
                    )
                    break

                # Sleep interruptibly until interval elapses or stop_event is set
                if self.stop_event.wait(timeout=interval):
                    break

        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING("\nKeyboardInterrupt detected. Terminating..."))
            logger.info("KeyboardInterrupt caught by mempool processor command.")
        finally:
            self.stdout.write(
                self.style.SUCCESS(
                    f"==========================================================\n"
                    f" MYCOIN Mempool Processor Stopped cleanly.\n"
                    f" Total cycles executed: {iteration}\n"
                    f"=========================================================="
                )
            )
            logger.info("Mempool processor stopped cleanly after %d cycles.", iteration)

    def _report_result(self, result: MempoolProcessingResult):
        """Formats and outputs the structured processing cycle outcome."""
        status = result.status
        if status in ["BATCH_PROCESSED", "BATCH_SELECTED"]:
            if result.produced_block_height is not None:
                msg = (
                    f"SUCCESS: Produced Block #{result.produced_block_height} "
                    f"({result.produced_block_hash[:12]}...) with {result.selected_count} "
                    f"transaction(s) for Chain {result.chain_id} in {result.duration_seconds:.4f}s."
                )
            else:
                msg = (
                    f"SUCCESS: Selected {result.selected_count}/{result.total_eligible_count} "
                    f"transaction(s) for Chain {result.chain_id} in {result.duration_seconds:.4f}s."
                )
            self.stdout.write(self.style.SUCCESS(f"  -> {msg}"))
            for idx, tx in enumerate(result.transactions, 1):
                tx_obj = tx.transaction
                tx_hash = getattr(tx_obj, "hash", getattr(tx_obj, "txHash", "unknown"))
                sender_addr = getattr(tx_obj.sender, "address", "unknown") if tx_obj.sender else "unknown"
                receiver_addr = getattr(tx_obj, "receiverAddress", "unknown")
                self.stdout.write(
                    f"     [{idx}] Hash: {tx_hash[:16]}... "
                    f"| From: {sender_addr[:10]}... "
                    f"| To: {receiver_addr[:10]}... "
                    f"| Value: {tx_obj.amount} "
                    f"| GasPrice: {tx_obj.gasPrice} "
                    f"| Status: {getattr(tx_obj, 'status', 'UNKNOWN')}"
                )

        elif status == "EMPTY":
            self.stdout.write(
                self.style.WARNING(
                    f"  -> Mempool is empty. 0 transactions available. Waiting for next cycle ({result.duration_seconds:.4f}s)."
                )
            )

        elif status == "LOCK_UNAVAILABLE":
            self.stdout.write(
                self.style.NOTICE(
                    f"  -> Lock held by another processor worker. Skipping cycle ({result.duration_seconds:.4f}s)."
                )
            )

        elif status == "NO_BLOCKCHAIN":
            self.stdout.write(
                self.style.ERROR(
                    f"  -> No active blockchain found! Please seed or activate a blockchain network."
                )
            )

        else:
            self.stdout.write(
                self.style.ERROR(
                    f"  -> Mempool processing returned status '{status}': {result.message}"
                )
            )
