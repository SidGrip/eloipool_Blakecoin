# Eloipool - Python Bitcoin pool server
# Copyright (C) 2011-2012  Luke Dashjr <luke-jr+eloipool@utopios.org>
# Portions written by Carlos Pizarro <kr105@kr105.com>
# Portions written by BlueDragon747 for the Blakecoin Project
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

from base58 import b58decode
from util import blakehash
from bitcoin import segwit_addr

WitnessMagic = b'\xaa\x21\xa9\xed'

# Bech32 HRPs accepted as valid SegWit pool payouts on Blakecoin networks.
# mainnet: blc, testnet: tblc, regtest: rblc, devnet: dblk
SEGWIT_HRPS = ('dblk', 'blc', 'tblc', 'rblc')

def _Address2PKH(addr):
	try:
		# The staged tree can resolve `base58` from either the pip package or
		# the older vendored helper. They expose different b58decode
		# signatures, so accept both to keep address parsing stable.
		try:
			addr = b58decode(addr, None)
		except TypeError:
			addr = b58decode(addr)
	except:
		return None
	if addr is None:
		return None
	if len(addr) != 25:
		return None
	ver = addr[0]
	cksumA = addr[-4:]
	cksumB = blakehash(addr[:-4])[:4]
	if cksumA != cksumB:
		return None
	return (ver, addr[1:-4])

class BitcoinScript:
	# Blakecoin address versions (decimal version byte from chainparams.cpp)
	# Mainnet P2PKH = 25/26 (0x19/0x1a)
	# Testnet P2PKH = 142 (0x8e)
	# Regtest P2PKH = 26 (0x1a)
	# Devnet  P2PKH = 65 (0x41) -- T-prefix
	# Mainnet P2SH  = 22 (0x16)
	# Testnet P2SH  = 170 (0xaa)
	# Regtest P2SH  = 7 (0x07)
	# Devnet  P2SH  = 120 (0x78) -- q-prefix
	P2PKH_VERSIONS = (0, 25, 26, 65, 111, 142)
	P2SH_VERSIONS = (5, 7, 22, 120, 127, 170, 196)

	@classmethod
	def toAddress(cls, addr):
		# Bech32 SegWit (devnet dblk1..., mainnet blc1...)
		hrp = addr.split('1', 1)[0].lower() if '1' in addr else ''
		if hrp in SEGWIT_HRPS:
			(witver, witprog) = segwit_addr.decode(hrp, addr)
			if witver is None:
				raise ValueError('invalid bech32 address: %s' % (addr,))
			# witver 0: P2WPKH (20-byte hash) or P2WSH (32-byte hash)
			if witver == 0:
				op_n = b'\x00'
			else:
				op_n = bytes((0x50 + witver,))  # OP_1..OP_16
			return op_n + bytes((len(witprog),)) + bytes(witprog)

		# Legacy base58check (P2PKH / P2SH)
		d = _Address2PKH(addr)
		if not d:
			raise ValueError('invalid address')
		(ver, pubkeyhash) = d
		if ver in cls.P2PKH_VERSIONS:
			return b'\x76\xa9\x14' + pubkeyhash + b'\x88\xac'
		elif ver in cls.P2SH_VERSIONS:
			return b'\xa9\x14' + pubkeyhash + b'\x87'
		raise ValueError('invalid address version: %d (expected P2PKH: %s or P2SH: %s)' % (ver, cls.P2PKH_VERSIONS, cls.P2SH_VERSIONS))
	
	@classmethod
	def commitment(cls, commitment):
		clen = len(commitment)
		if clen > 0x4b:
			raise NotImplementedError
		return b'\x6a' + bytes((clen,)) + commitment

def countSigOps(s):
	# FIXME: don't count data as ops
	c = 0
	for ch in s:
		if 0xac == ch & 0xfe:
			c += 1
		elif 0xae == ch & 0xfe:
			c += 20
	return c

# NOTE: This does not work for signed numbers (set the high bit) or zero (use b'\0')
def encodeUNum(n):
	s = bytearray(b'\1')
	while n > 127:
		s[0] += 1
		s.append(n % 256)
		n //= 256
	s.append(n)
	return bytes(s)

def encodeNum(n):
	if n == 0:
		return b'\0'
	if n > 0:
		return encodeUNum(n)
	s = encodeUNum(abs(n))
	s = bytearray(s)
	s[-1] = s[-1] | 0x80
	return bytes(s)

# tests
def _test():
	assert b'\0' == encodeNum(0)
	assert b'\1\x55' == encodeNum(0x55)
	assert b'\2\xfd\0' == encodeNum(0xfd)
	assert b'\3\xff\xff\0' == encodeNum(0xffff)
	assert b'\3\0\0\x01' == encodeNum(0x10000)
	assert b'\5\xff\xff\xff\xff\0' == encodeNum(0xffffffff)

_test()
