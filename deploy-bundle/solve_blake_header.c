#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "sph_blake.h"

static int hex_value(char c)
{
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return 10 + (c - 'a');
    if (c >= 'A' && c <= 'F') return 10 + (c - 'A');
    return -1;
}

static int parse_hex(const char* hex, unsigned char* out, size_t out_len)
{
    size_t hex_len = strlen(hex);
    size_t expected = out_len * 2;
    size_t i;

    if (hex_len != expected) {
        return 0;
    }

    for (i = 0; i < out_len; ++i) {
        int hi = hex_value(hex[i * 2]);
        int lo = hex_value(hex[i * 2 + 1]);
        if (hi < 0 || lo < 0) {
            return 0;
        }
        out[i] = (unsigned char)((hi << 4) | lo);
    }

    return 1;
}

static void hash_blake_header(const unsigned char header[80], unsigned char out[32])
{
    sph_blake256_context ctx;
    sph_blake256_init(&ctx);
    sph_blake256(&ctx, header, 80);
    sph_blake256_close(&ctx, out);
}

static void compact_to_target(uint32_t compact, unsigned char target[32])
{
    int exponent = (int)(compact >> 24);
    uint32_t mantissa = compact & 0x007fffffU;
    int i;

    memset(target, 0, 32);

    if (mantissa == 0) {
        return;
    }

    if (exponent <= 3) {
        mantissa >>= 8 * (3 - exponent);
        for (i = 0; i < 4 && mantissa != 0; ++i) {
            target[i] = (unsigned char)(mantissa & 0xffU);
            mantissa >>= 8;
        }
        return;
    }

    {
        int shift = exponent - 3;
        for (i = 0; i < 3; ++i) {
            int index = shift + i;
            if (index >= 0 && index < 32) {
                target[index] = (unsigned char)((mantissa >> (8 * i)) & 0xffU);
            }
        }
    }
}

static int hash_meets_target(const unsigned char hash[32], const unsigned char target[32])
{
    int i;
    for (i = 31; i >= 0; --i) {
        if (hash[i] < target[i]) {
            return 1;
        }
        if (hash[i] > target[i]) {
            return 0;
        }
    }
    return 1;
}

static uint32_t read_le32(const unsigned char* p)
{
    return ((uint32_t)p[0]) |
           ((uint32_t)p[1] << 8) |
           ((uint32_t)p[2] << 16) |
           ((uint32_t)p[3] << 24);
}

static void write_le32(unsigned char* p, uint32_t value)
{
    p[0] = (unsigned char)(value & 0xffU);
    p[1] = (unsigned char)((value >> 8) & 0xffU);
    p[2] = (unsigned char)((value >> 16) & 0xffU);
    p[3] = (unsigned char)((value >> 24) & 0xffU);
}

static void print_hash_hex(const unsigned char hash[32])
{
    int i;
    for (i = 31; i >= 0; --i) {
        printf("%02x", hash[i]);
    }
}

int main(int argc, char** argv)
{
    unsigned char header[80];
    unsigned char target[32];
    unsigned char hash[32];
    uint32_t compact;
    uint32_t start_nonce;
    uint32_t nonce;

    if (argc != 2) {
        fprintf(stderr, "usage: %s <80-byte-header-hex>\n", argv[0]);
        return 1;
    }

    if (!parse_hex(argv[1], header, sizeof(header))) {
        fprintf(stderr, "invalid header hex\n");
        return 1;
    }

    compact = read_le32(header + 72);
    compact_to_target(compact, target);
    start_nonce = read_le32(header + 76);

    for (nonce = start_nonce;; ++nonce) {
        write_le32(header + 76, nonce);
        hash_blake_header(header, hash);
        if (hash_meets_target(hash, target)) {
            printf("%u ", nonce);
            print_hash_hex(hash);
            printf("\n");
            return 0;
        }
        if (nonce == 0xffffffffU) {
            break;
        }
    }

    fprintf(stderr, "no valid nonce found\n");
    return 2;
}
