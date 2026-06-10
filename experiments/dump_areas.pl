#!/usr/bin/perl
# Dump per-leaf areas from a .dom using Urb itself (ground truth for validating
# the Python geometry port). Run from the urb repo root with -Ilib.
# Output matches experiments/dump_areas.py: "level/idpath type area", sorted.
use strict;
use warnings;
use YAML;
use Urb::Dom;

my $dom = Urb::Dom->new;
$dom->Deserialise (YAML::LoadFile ($ARGV[0]));

my @rows;
for my $level ($dom, $dom->Levels_Above)
{
    my $lid = scalar $level->Levels_Below;
    for my $leaf ($level->Leafs)
    {
        my $type = $leaf->Type || '?';
        push @rows, sprintf ("%d/%s %s %.4f", $lid, $leaf->Id, $type, $leaf->Area);
    }
}
print join ("\n", sort @rows), "\n";
