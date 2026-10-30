"""Testes unitarios sem bibliotecas externas. Execute: python -m unittest discover -s tests -v"""
import asyncio
import hashlib
import tempfile
import unittest
from pathlib import Path

from p2p.protocol import ProtocolError, read_frame, send_frame
from p2p.storage import BlockStore, create_manifest, sha256_file, validate_manifest


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.source = self.root / "arquivo.bin"
        self.source.write_bytes(bytes(range(256)) * 9 + b"final")
        self.meta = create_manifest(self.source, 1024)

    def tearDown(self):
        self.tmp.cleanup()

    def test_manifest_and_number_of_blocks(self):
        self.assertEqual(self.meta["size"], 2309)
        self.assertEqual(len(self.meta["block_hashes"]), 3)
        self.assertEqual(self.meta["sha256"], sha256_file(self.source))

    def test_seeder_has_all_blocks(self):
        seed = BlockStore(self.root / "seed", self.meta, self.source)
        self.assertEqual(seed.count, 3)
        self.assertEqual(seed.read_block(2), self.source.read_bytes()[2048:])

    def test_out_of_order_and_finalize(self):
        async def run():
            seed = BlockStore(self.root / "seed", self.meta, self.source)
            leecher = BlockStore(self.root / "leecher", self.meta)
            for i in (2, 0, 1):
                self.assertTrue(await leecher.save_block(i, seed.read_block(i)))
            self.assertFalse(await leecher.save_block(1, seed.read_block(1)))
            self.assertEqual(leecher.finalize().read_bytes(), self.source.read_bytes())
        asyncio.run(run())

    def test_reject_modified_block(self):
        async def run():
            leecher = BlockStore(self.root / "leecher", self.meta)
            with self.assertRaises(ProtocolError):
                await leecher.save_block(0, b"z" * 1024)
            self.assertEqual(leecher.count, 0)
        asyncio.run(run())

    def test_resume_with_verification(self):
        async def run():
            seed = BlockStore(self.root / "seed", self.meta, self.source)
            leo = self.root / "leecher"
            store = BlockStore(leo, self.meta)
            await store.save_block(2, seed.read_block(2))
            restored = BlockStore(leo, self.meta)
            self.assertEqual(restored.count, 1)
            with (leo / "downloads" / (self.meta["file_name"] + ".part")).open("r+b") as f:
                f.seek(2048)
                f.write(b"corrupted")
            verified = BlockStore(leo, self.meta)
            self.assertEqual(verified.count, 0)
        asyncio.run(run())

    def test_unsafe_filename_is_rejected(self):
        malicious = dict(self.meta, file_name="../intruso.txt")
        with self.assertRaises(ProtocolError):
            validate_manifest(malicious)

    def test_empty_file(self):
        self.source.write_bytes(b"")
        meta = create_manifest(self.source, 4096)
        self.assertEqual(meta["block_hashes"], [])
        store = BlockStore(self.root / "empty", meta)
        self.assertEqual(store.finalize().stat().st_size, 0)
        self.assertEqual(meta["sha256"], hashlib.sha256(b"").hexdigest())


class ProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_framing_with_binary_payload(self):
        received = []

        async def handle(reader, writer):
            received.append(await read_frame(reader))
            await send_frame(writer, {"type": "ack"})
            writer.close()
            await writer.wait_closed()

        server = await asyncio.start_server(handle, "127.0.0.1", 0)
        try:
            port = server.sockets[0].getsockname()[1]
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            await send_frame(writer, {"type": "block", "index": 0}, b"\x00\xff\x00\xfe")
            reply, _ = await read_frame(reader)
            self.assertEqual(reply["type"], "ack")
            self.assertEqual(received[0][1], b"\x00\xff\x00\xfe")
            writer.close()
            await writer.wait_closed()
        finally:
            server.close()
            await server.wait_closed()


if __name__ == "__main__":
    unittest.main()
