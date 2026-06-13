#!/usr/bin/perl
# Parity oracle for homemaker-py-gnw: per-leaf quality factors and per-storey
# cost/value from Urb's programme-driven fitness.
#
# Stock urb-fitness.pl cannot emit the per-leaf DEBUG lines: Leaf.pm/Storey.pm
# copy $Urb::Dom::Fitness::DEBUG into a package var at *compile* time, before
# Fitness.pm's own `our $DEBUG = $ENV{DEBUG}` line has run, so the flag is
# permanently false.  This wrapper sets those package vars after loading and
# also wraps process_storey to print each storey's cost/value subtotal.
#
# Usage (from the corpus directory, URB_NO_OCCLUSION required):
#   cd examples/programme-house
#   URB_NO_OCCLUSION=1 perl -I$URB/lib dump_leaf_quality.pl a.dom b.dom ...
#
# Output (stdout):
#   === FILE <name>
#   ...Leaf.pm debug lines ('  quality perpendicular: <f>' x7, then
#      'leaf level: L id: I type: T rate: R area: A width: W proportion: P')
#   STOREY <level_id> cost: <c> value: <v>
#   INITIAL_COST <c>
#   FAIL <message>            (one per failure)
#   SCORE <fitness>

use strict;
use warnings;
use 5.010;
use Urb::Dom;
use Urb::Dom::Fitness;
use Urb::Dom::Fitness::ProgrammeDriven;
use YAML;
use Carp;

die "URB_NO_OCCLUSION=1 required: native fitness ports simple crinkliness only\n"
    unless $ENV{URB_NO_OCCLUSION};

# Re-enable the per-leaf/storey debug gates (see header) and route everything
# to STDOUT so output interleaves deterministically.
$Urb::Dom::Fitness::Leaf::DEBUG = 1;
$Urb::Dom::Fitness::Storey::DEBUG = 1;
$Urb::Dom::Fitness::DEBUG = 1;
{
    no warnings 'redefine';
    *Urb::Dom::Fitness::debug = sub { print join(' ', @_), "\n"; return 1 };
    *Urb::Dom::Fitness::Base::debug = sub {
        my @text = @_;
        shift @text if ref $text[0];    # method form: drop $self
        print join(' ', @text), "\n";
        return 1;
    };
}

my $orig_process_storey = \&Urb::Dom::Fitness::Storey::process_storey;
{
    no warnings 'redefine';
    *Urb::Dom::Fitness::Storey::process_storey = sub {
        my @args = @_;
        my $result = $orig_process_storey->(@args);
        printf "STOREY %s cost: %.17g value: %.17g\n",
            $args[5], $result->{cost}, $result->{value};
        return $result;
    };
}

# Config loading exactly as urb-fitness.pl (project-level then local).
my $config = undef;
for my $path ('../patterns.config', 'patterns.config')
{
    next unless -e $path;
    my $config_temp = YAML::LoadFile ($path);
    $config->{$_} = $config_temp->{$_} for keys %{$config_temp};
}
my $costs = undef;
for my $path ('../costs.config', 'costs.config')
{
    next unless -e $path;
    my $costs_temp = YAML::LoadFile ($path);
    $costs->{$_} = $costs_temp->{$_} for keys %{$costs_temp};
}

die "no spaces config: wrapper only supports programme-driven mode\n"
    unless $config && exists $config->{spaces};
my $assessor = Urb::Dom::Fitness::ProgrammeDriven->new ($config, $costs);

for my $path_yaml (@ARGV)
{
    my @items = YAML::LoadFile ($path_yaml);
    next unless scalar @items;
    my $dom = Urb::Dom->new;
    $dom->Deserialise (@items);

    say "=== FILE $path_yaml";
    printf "INITIAL_COST %.17g\n", $assessor->Cost ('plot') * $dom->Area;
    my $score = $assessor->_apply ($dom);
    say "FAIL $_" for ($dom->Failures);
    printf "SCORE %.17g\n", $score;
    $dom->DESTROY;
}

0;
